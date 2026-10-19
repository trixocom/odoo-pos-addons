# Part of trx_supplier_pricelist_revision. Author: Trixocom. License: LGPL-3.
import base64
import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

from .. import file_parser
from .res_partner import PVP_ROUNDINGS, PVP_RULES

_logger = logging.getLogger(__name__)

STATES = [
    ("draft", "Borrador"),
    ("review", "En revisión"),
    ("scheduled", "Programada"),
    ("applied", "Aplicada"),
    ("cancelled", "Cancelada"),
]


class TrxSupplierPricelistRevision(models.Model):
    _name = "trx.supplier.pricelist.revision"
    _description = "Lista de proveedor / Revisión de precios"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Número", required=True, copy=False, readonly=True, default=lambda self: _("Nuevo"))
    partner_id = fields.Many2one(
        "res.partner", string="Proveedor", required=True, index=True, tracking=True,
        domain="[('supplier_rank', '>', 0)]",
    )
    file = fields.Binary(string="Archivo original", attachment=True, copy=False)
    file_name = fields.Char(string="Nombre del archivo", copy=False)
    file_sheet = fields.Char(string="Hoja leída", readonly=True, copy=False)
    file_columns = fields.Char(string="Columnas reconocidas", readonly=True, copy=False)
    date_received = fields.Date(string="Fecha de recepción", default=fields.Date.context_today, tracking=True)
    state = fields.Selection(STATES, string="Estado", default="draft", required=True, tracking=True, copy=False, index=True)
    discount_pct = fields.Float(string="Descuento del proveedor %", digits="Discount",
                                help="Bonificación sobre el precio de lista. Costo neto = lista × (1 − %). "
                                     "Si la lista trae una columna de bonificación, se usa la de cada línea.")
    pvp_rule = fields.Selection(PVP_RULES, string="Regla de PVP", required=True, default="list_factor", tracking=True)
    pvp_factor = fields.Float(string="Factor", digits=(16, 4), default=2.0)
    pvp_rounding = fields.Selection(PVP_ROUNDINGS, string="Redondeo", default="1", required=True)
    keep_pvp_on_decrease = fields.Boolean(
        string="No bajar el PVP cuando baja el costo", default=True, tracking=True,
        help="Si el costo baja, el PVP propuesto es el actual (decisión 'Aplicar costo, mantener PVP'). "
             "Se puede cambiar línea por línea o con el filtro 'Bajaron'.",
    )
    apply_at = fields.Datetime(string="Aplicar desde", tracking=True, copy=False,
                               help="Fecha y hora en que entran en vigencia los precios nuevos.")
    applied_at = fields.Datetime(string="Aplicada el", readonly=True, copy=False)
    apply_user_id = fields.Many2one("res.users", string="Aplicada por", readonly=True, copy=False)
    note = fields.Text(string="Notas")
    company_id = fields.Many2one("res.company", string="Razón social", default=lambda self: self.env.company,
                                 help="Sólo para la moneda. Las listas de proveedor y el PVP son de toda la red.")
    currency_id = fields.Many2one(related="company_id.currency_id")
    line_ids = fields.One2many("trx.supplier.pricelist.revision.line", "revision_id", string="Líneas", copy=False)

    line_count = fields.Integer(compute="_compute_counts")
    count_up = fields.Integer(string="Subieron", compute="_compute_counts")
    count_down = fields.Integer(string="Bajaron", compute="_compute_counts")
    count_equal = fields.Integer(string="Iguales", compute="_compute_counts")
    count_new = fields.Integer(string="Nuevos", compute="_compute_counts")
    count_no_pvp = fields.Integer(string="Sin PVP", compute="_compute_counts")
    count_suggested = fields.Integer(string="Sugeridos", compute="_compute_counts")

    @api.depends("line_ids.trend", "line_ids.pvp_proposed", "line_ids.match_state")
    def _compute_counts(self):
        for rec in self:
            lines = rec.line_ids
            rec.line_count = len(lines)
            rec.count_up = len(lines.filtered(lambda l: l.trend == "up"))
            rec.count_down = len(lines.filtered(lambda l: l.trend == "down"))
            rec.count_equal = len(lines.filtered(lambda l: l.trend == "equal"))
            rec.count_new = len(lines.filtered(lambda l: l.match_state == "new"))
            rec.count_suggested = len(lines.filtered(lambda l: l.match_state in ("suggested", "unresolved")))
            rec.count_no_pvp = len(lines.filtered(lambda l: l.match_state == "matched" and not l.pvp_proposed))

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.partner_id:
            self.discount_pct = self.partner_id.trx_pricelist_discount
            self.pvp_rule = self.partner_id.trx_pvp_rule or "list_factor"
            self.pvp_factor = self.partner_id.trx_pvp_factor or 2.0
            self.pvp_rounding = self.partner_id.trx_pvp_rounding or "1"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code("trx.supplier.pricelist.revision") or _("Nuevo")
            partner = self.env["res.partner"].browse(vals.get("partner_id")) if vals.get("partner_id") else None
            if partner:
                vals.setdefault("discount_pct", partner.trx_pricelist_discount)
                vals.setdefault("pvp_rule", partner.trx_pvp_rule or "list_factor")
                vals.setdefault("pvp_factor", partner.trx_pvp_factor or 2.0)
                vals.setdefault("pvp_rounding", partner.trx_pvp_rounding or "1")
        return super().create(vals_list)

    def unlink(self):
        if any(rec.state in ("scheduled", "applied") for rec in self):
            raise UserError(_("No se puede borrar una lista programada o aplicada. Cancelala si hace falta."))
        return super().unlink()

    # ------------------------------------------------------------------ carga
    def action_load_file(self):
        self.ensure_one()
        if self.state not in ("draft", "review"):
            raise UserError(_("Sólo se pueden cargar líneas en borrador o en revisión."))
        if not self.file:
            raise UserError(_("Subí primero el archivo del proveedor."))
        content = base64.b64decode(self.file)
        try:
            parsed = file_parser.parse(content, self.file_name or "")
        except Exception as e:  # noqa: BLE001
            _logger.exception("No se pudo leer la lista %s", self.file_name)
            raise UserError(_("No se pudo leer el archivo %s: %s", self.file_name, e)) from e
        if not parsed:
            raise UserError(_(
                "No se reconocieron las columnas de la lista. Hacen falta al menos una columna de código y una de precio "
                "(por ejemplo: Código, Detalle, Precio de lista, Bonificación, Código de barras, Sugerido)."
            ))
        sheet, header_map, rows = parsed
        self.line_ids.unlink()
        vals_list = []
        for seq, item in enumerate(rows, start=1):
            vals_list.append({
                "revision_id": self.id,
                "sequence": seq,
                "supplier_code": item["code"],
                "supplier_name": item["name"] or item["code"],
                "barcode": item["barcode"] or False,
                "list_price": item["list_price"],
                "discount_pct": item["discount"] if item["discount"] is not None else self.discount_pct,
                "suggested_pvp": item["suggested"] or 0.0,
            })
        lines = self.env["trx.supplier.pricelist.revision.line"].create(vals_list)
        self.write({
            "file_sheet": sheet,
            "file_columns": ", ".join("%s=col %s" % (k, v + 1) for k, v in header_map.items()),
            "state": "review",
        })
        lines._match_products()
        lines._snapshot_current()
        lines._compute_proposals(force=True)
        self.message_post(body=_(
            "Lista cargada desde %s (hoja %s): %s líneas. Subieron %s, bajaron %s, iguales %s, nuevos %s.",
            self.file_name, sheet, len(lines), self.count_up, self.count_down, self.count_equal, self.count_new,
        ))
        return True

    def action_recompute(self):
        """Vuelve a reconocer artículos, tomar valores actuales y proponer PVP (respeta los PVP editados a mano)."""
        for rec in self:
            if rec.state not in ("draft", "review"):
                raise UserError(_("Sólo en revisión."))
            rec.line_ids._match_products()
            rec.line_ids._snapshot_current()
            rec.line_ids._compute_proposals(force=False)
        return True

    def action_recompute_pvp_all(self):
        """Recalcula el PVP propuesto de todas las líneas con la regla del documento (pisa lo editado a mano)."""
        for rec in self:
            rec.line_ids._compute_proposals(force=True)
        return True

    # ------------------------------------------------------------- programación
    def _default_apply_at(self):
        """Mañana a las 00:00 en el huso horario del usuario, expresado en UTC."""
        tz = pytz.timezone(self.env.user.tz or "America/Argentina/Buenos_Aires")
        local_tomorrow = datetime.combine(fields.Date.context_today(self) + timedelta(days=1), time.min)
        return tz.localize(local_tomorrow).astimezone(pytz.utc).replace(tzinfo=None)

    def action_schedule(self):
        for rec in self:
            if rec.state != "review":
                raise UserError(_("Sólo se puede programar una lista en revisión."))
            if not rec.line_ids:
                raise UserError(_("La lista no tiene líneas."))
            if not rec.apply_at:
                rec.apply_at = rec._default_apply_at()
            rec.state = "scheduled"
            rec.message_post(body=_("Programada para aplicar el %s.", fields.Datetime.context_timestamp(rec, rec.apply_at).strftime("%d/%m/%Y %H:%M")))
            cron = self.env.ref("trx_supplier_pricelist_revision.ir_cron_apply_scheduled", raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger(at=rec.apply_at if rec.apply_at > fields.Datetime.now() else None)
        return True

    def action_back_to_review(self):
        for rec in self:
            if rec.state != "scheduled":
                raise UserError(_("Sólo una lista programada puede volver a revisión."))
            rec.state = "review"
        return True

    def action_apply_now(self):
        for rec in self:
            if rec.state not in ("review", "scheduled"):
                raise UserError(_("Sólo se puede aplicar una lista en revisión o programada."))
            if not rec.line_ids:
                raise UserError(_("La lista no tiene líneas."))
            rec.apply_at = fields.Datetime.now()
            rec._apply()
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == "applied":
                raise UserError(_("Una lista aplicada no se puede cancelar: los precios ya están vigentes."))
            rec.state = "cancelled"
        return True

    def action_draft(self):
        for rec in self:
            if rec.state != "cancelled":
                raise UserError(_("Sólo una lista cancelada puede volver a borrador."))
            rec.state = "draft"
        return True

    @api.model
    def _cron_apply_scheduled(self):
        now = fields.Datetime.now()
        due = self.search([("state", "=", "scheduled"), ("apply_at", "<=", now)], order="apply_at, id")
        for rec in due:
            try:
                with self.env.cr.savepoint():
                    rec._apply()
            except Exception:  # noqa: BLE001
                _logger.exception("No se pudo aplicar la lista programada %s", rec.name)
                rec.message_post(body=_("Falló la aplicación programada; revisá el log del servidor."))
                rec.activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=_("Falló la aplicación de la lista %s", rec.name),
                    user_id=rec.create_uid.id,
                )
        return True

    # ---------------------------------------------------------------- aplicar
    def _get_discount_rule(self, discount_pct):
        """Regla de costo de reposición (ADHOC) 'Descuento de lista X %' → net_price = lista × (1 − X %)."""
        self.ensure_one()
        prec = self.env["decimal.precision"].precision_get("Discount")
        if float_is_zero(discount_pct, precision_digits=prec):
            return self.env["product.replenishment_cost.rule"]
        Rule = self.env["product.replenishment_cost.rule"]
        name = _("Descuento de lista %s %%", ("%.2f" % discount_pct).rstrip("0").rstrip("."))
        rule = Rule.search([("name", "=", name)], limit=1)
        if not rule:
            rule = Rule.create({
                "name": name,
                "item_ids": [(0, 0, {
                    "name": _("Descuento"), "percentage_amount": -discount_pct, "fixed_amount": 0.0, "add_to_cost": True,
                })],
            })
        return rule

    def _history_context(self):
        self.ensure_one()
        return {
            "trx_price_history_origin": "revision",
            "trx_price_history_ref": self.name,
            "trx_price_history_reason": _("Lista %s del %s", self.partner_id.name, self.date_received or ""),
            "trx_price_history_date": self.apply_at or fields.Datetime.now(),
        }

    def _apply(self):
        self.ensure_one()
        if self.state == "applied":
            return True
        prec = self.env["decimal.precision"].precision_get("Product Price")
        ctx = self._history_context()
        Seller = self.env["product.supplierinfo"].with_context(**ctx)
        apply_date = fields.Datetime.context_timestamp(self, self.apply_at or fields.Datetime.now()).date()
        applied = skipped = 0
        for line in self.line_ids:
            if line.state == "applied":
                continue
            tmpl = line.product_tmpl_id
            if line.decision not in ("apply", "keep_pvp") or not tmpl or line.match_state != "matched":
                line.state = "skipped"
                skipped += 1
                continue
            rule = self._get_discount_rule(line.discount_pct)
            seller = Seller.search([
                ("partner_id", "=", self.partner_id.id), ("product_tmpl_id", "=", tmpl.id), ("company_id", "=", False),
            ], order="sequence, id", limit=1) or Seller.search([
                ("partner_id", "=", self.partner_id.id), ("product_tmpl_id", "=", tmpl.id),
            ], order="sequence, id", limit=1)
            seller_vals = {
                "price": line.list_price,
                "discount": 0.0,
                "replenishment_cost_rule_id": rule.id or False,
                "product_code": line.supplier_code or False,
                "product_name": line.supplier_name or False,
                "date_start": apply_date,
                "date_end": False,
            }
            if seller:
                seller.write(seller_vals)
            else:
                seller_vals.update({
                    "partner_id": self.partner_id.id, "product_tmpl_id": tmpl.id, "company_id": False, "min_qty": 0,
                })
                seller = Seller.create(seller_vals)
            tmpl_vals = {}
            if tmpl.replenishment_cost_type == "manual" and float_is_zero(tmpl.replenishment_base_cost, precision_digits=prec):
                tmpl_vals["replenishment_cost_type"] = "supplier_price"
            if (
                line.decision == "apply"
                and line.pvp_proposed > 0
                and float_compare(line.pvp_proposed, tmpl.list_price, precision_digits=prec) != 0
            ):
                tmpl_vals["list_price"] = line.pvp_proposed
            if tmpl_vals:
                tmpl.with_context(**ctx).write(tmpl_vals)
            line.write({"state": "applied", "supplierinfo_id": seller.id})
            applied += 1
        self.write({"state": "applied", "applied_at": fields.Datetime.now(), "apply_user_id": self.env.uid})
        self.message_post(body=_(
            "Lista aplicada: %s líneas aplicadas, %s no incorporadas. Vigencia %s.",
            applied, skipped, fields.Datetime.context_timestamp(self, self.apply_at).strftime("%d/%m/%Y %H:%M"),
        ))
        return True

    # ------------------------------------------------------------------ vistas
    def _action_lines(self, name, domain_extra=None, context_extra=None):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "trx_supplier_pricelist_revision.action_trx_supplier_pricelist_revision_line"
        )
        action["name"] = "%s · %s" % (self.name, name)
        action["domain"] = [("revision_id", "=", self.id)] + (domain_extra or [])
        action["context"] = dict(self.env.context, default_revision_id=self.id, search_default_revision_id=self.id,
                                 **(context_extra or {}))
        return action

    def action_view_lines(self):
        return self._action_lines(_("Líneas"))

    def action_view_lines_up(self):
        return self._action_lines(_("Subieron"), [("trend", "=", "up")])

    def action_view_lines_down(self):
        return self._action_lines(_("Bajaron"), [("trend", "=", "down")])

    def action_view_lines_equal(self):
        return self._action_lines(_("Iguales"), [("trend", "=", "equal")])

    def action_view_lines_new(self):
        return self._action_lines(_("Nuevos"), [("match_state", "=", "new")])

    def action_view_lines_no_pvp(self):
        return self._action_lines(_("Sin PVP"), [("match_state", "=", "matched"), ("pvp_proposed", "<=", 0)])

    def action_view_lines_suggested(self):
        return self._action_lines(_("A confirmar"), [("match_state", "in", ("suggested", "unresolved"))])
