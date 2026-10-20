# Part of trx_purchase_ai_inbox. Author: Trixocom. License: LGPL-3.
import json
import logging
import re
import unicodedata
from datetime import date, datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

from odoo.addons.trx_pos_price_sync.models.pos_price_sync import _register_for_sync

from .inbox_perception import KINDS, classify

_logger = logging.getLogger(__name__)

# letra → código AFIP del tipo de comprobante "Factura"
INVOICE_DOC_CODES = {"A": "1", "B": "6", "C": "11", "M": "51", "E": "19"}
CREDIT_NOTE_DOC_CODES = {"A": "3", "B": "8", "C": "13", "M": "53", "E": "21"}

STATES = [
    ("draft", "Nueva"),
    ("scanned", "Leída"),
    ("review", "A revisar"),
    ("done", "OC generada"),
    ("rejected", "Rechazada"),
]


def _digits(value):
    return re.sub(r"\D", "", value or "")


def _to_date(value):
    if not value:
        return False
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(value).strip()[:10], fmt).date()
        except ValueError:
            continue
    return False


def _num(value):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


class TrxPurchaseInbox(models.Model):
    _name = "trx.purchase.inbox"
    _description = "Factura de proveedor recibida (escaneo IA)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Número", required=True, copy=False, readonly=True, default=lambda self: _("Nueva"))
    company_id = fields.Many2one("res.company", string="Razón social que compra", required=True,
                                 default=lambda self: self.env.company, tracking=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    file = fields.Binary(string="Factura (PDF, foto o Word)", attachment=True, copy=False)
    file_name = fields.Char(string="Archivo", copy=False)
    state = fields.Selection(STATES, default="draft", required=True, tracking=True, copy=False, index=True)
    reject_reason = fields.Char(string="Motivo de rechazo", readonly=True, copy=False)

    partner_id = fields.Many2one("res.partner", string="Proveedor", tracking=True, domain="[('is_company', '=', True)]")
    partner_created = fields.Boolean(string="Proveedor creado desde la factura", readonly=True)
    issuer_name = fields.Char(string="Razón social impresa", readonly=True)
    issuer_vat = fields.Char(string="CUIT emisor", readonly=True)
    receiver_name = fields.Char(string="Receptor impreso", readonly=True)
    receiver_vat = fields.Char(string="CUIT receptor", readonly=True)
    doc_type = fields.Char(string="Tipo", readonly=True)
    doc_letter = fields.Char(string="Letra", readonly=True)
    doc_number = fields.Char(string="Número de comprobante", readonly=True)
    invoice_date = fields.Date(string="Fecha", readonly=True)
    invoice_date_due = fields.Date(string="Vencimiento", readonly=True)
    cae = fields.Char(string="CAE", readonly=True)
    cae_due = fields.Date(string="Vto. CAE", readonly=True)
    prices_include_tax = fields.Boolean(string="Precios con IVA incluido", readonly=True,
                                        help="Facturas B y C: los precios impresos son finales.")
    non_fiscal = fields.Boolean(string="Comprobante no fiscal (NF)", tracking=True,
                                help="Presupuesto, pedido o factura no fiscal pagada en efectivo: la orden de compra y la factura van sin IVA "
                                     "y la factura se registra en el diario de compras NF, que no maneja documentos (no se informa a ARCA).")
    global_discount_pct = fields.Float(string="Descuento global %", digits=(16, 4), readonly=True,
                                       help="Bonificación al pie, prorrateada sobre las líneas (suma de % y de importes).")
    global_discount_desc = fields.Char(string="Descuentos al pie", readonly=True)
    other_charges = fields.Monetary(string="Otros cargos (flete, etc.)", currency_field="currency_id", readonly=True)
    other_charges_desc = fields.Char(string="Detalle de otros cargos", readonly=True)
    amount_untaxed_printed = fields.Monetary(string="Neto impreso", currency_field="currency_id", readonly=True)
    amount_tax_printed = fields.Monetary(string="IVA impreso", currency_field="currency_id", readonly=True)
    amount_perceptions = fields.Monetary(string="Percepciones", currency_field="currency_id", compute="_compute_calc", store=True)
    perceptions_desc = fields.Char(string="Detalle de percepciones", readonly=True)
    amount_total_printed = fields.Monetary(string="Total impreso", currency_field="currency_id", readonly=True)
    amount_untaxed_calc = fields.Monetary(string="Neto calculado", currency_field="currency_id", compute="_compute_calc", store=True)
    amount_tax_calc = fields.Monetary(string="IVA calculado", currency_field="currency_id", compute="_compute_calc", store=True)
    amount_total_calc = fields.Monetary(string="Total calculado", currency_field="currency_id", compute="_compute_calc", store=True)
    amount_diff = fields.Monetary(string="Diferencia", currency_field="currency_id", compute="_compute_calc", store=True)
    totals_ok = fields.Boolean(string="Totales cierran", compute="_compute_calc", store=True)
    ai_notes = fields.Text(string="Observaciones de la lectura", readonly=True)
    ai_model = fields.Char(string="Modelo", readonly=True)
    ai_usage = fields.Char(string="Uso de tokens", readonly=True)
    ai_raw = fields.Text(string="Respuesta completa (JSON)", readonly=True)
    line_ids = fields.One2many("trx.purchase.inbox.line", "inbox_id", string="Líneas", copy=False)
    line_count = fields.Integer(compute="_compute_counts")
    count_matched = fields.Integer(compute="_compute_counts")
    count_new = fields.Integer(compute="_compute_counts")
    count_price_up = fields.Integer(compute="_compute_counts")
    picking_type_id = fields.Many2one(
        "stock.picking.type", string="Recibe en", check_company=True,
        domain="[('code', '=', 'incoming'), ('company_id', '=', company_id)]",
        help="Local / depósito donde entra la mercadería. La recepción aparece en la caja de ese local "
             "(Recepciones del POS). Si se deja vacío se usa el depósito por defecto de la razón social.")
    purchase_id = fields.Many2one("purchase.order", string="Orden de compra", readonly=True, copy=False)
    picking_count = fields.Integer(compute="_compute_counts")
    perception_ids = fields.One2many("trx.purchase.inbox.perception", "inbox_id", string="Percepciones", copy=False)
    perception_count = fields.Integer(compute="_compute_counts")
    invoice_id = fields.Many2one("account.move", string="Factura de proveedor", readonly=True, copy=False)
    note = fields.Text(string="Notas")

    @api.depends("line_ids.price_net_untaxed", "line_ids.qty", "line_ids.tax_rate", "perception_ids.amount", "other_charges",
                 "amount_total_printed", "non_fiscal")
    def _compute_calc(self):
        for rec in self:
            untaxed = sum(l.qty * l.price_net_untaxed for l in rec.line_ids)
            tax = 0.0 if rec.non_fiscal else sum(l.qty * l.price_net_untaxed * (l.tax_rate or 0.0) / 100.0 for l in rec.line_ids)
            perceptions = sum(rec.perception_ids.mapped("amount"))
            rec.amount_perceptions = perceptions
            total = untaxed + tax + perceptions + (rec.other_charges or 0.0)
            rec.amount_untaxed_calc = untaxed
            rec.amount_tax_calc = tax
            rec.amount_total_calc = total
            rec.amount_diff = total - (rec.amount_total_printed or 0.0)
            tol = max(1.0, (rec.amount_total_printed or 0.0) * 0.005)
            rec.totals_ok = bool(rec.amount_total_printed) and abs(rec.amount_diff) <= tol

    @api.depends("line_ids.match_state", "line_ids.price_up", "purchase_id", "perception_ids")
    def _compute_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.count_matched = len(rec.line_ids.filtered(lambda l: l.match_state == "matched"))
            rec.count_new = len(rec.line_ids.filtered(lambda l: l.match_state != "matched"))
            rec.count_price_up = len(rec.line_ids.filtered("price_up"))
            rec.picking_count = len(rec.purchase_id.picking_ids) if rec.purchase_id else 0
            rec.perception_count = len(rec.perception_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Nueva")) == _("Nueva"):
                vals["name"] = self.env["ir.sequence"].next_by_code("trx.purchase.inbox") or _("Nueva")
        return super().create(vals_list)

    # ------------------------------------------------------------------ escaneo
    def action_scan(self):
        for rec in self:
            if not rec.file:
                raise UserError(_("Subí primero la factura (PDF o foto)."))
            if rec.state == "done":
                raise UserError(_("Esta factura ya generó una orden de compra."))
            attachment = self.env["ir.attachment"].search([
                ("res_model", "=", rec._name), ("res_id", "=", rec.id), ("res_field", "=", "file")], limit=1)
            mimetype = attachment.mimetype if attachment else ""
            data, info = self.env["trx.purchase.ai.client"].extract_invoice(rec.file.decode() if isinstance(rec.file, bytes) else rec.file, mimetype, rec.file_name or "")
            rec._apply_result(data, info)
        return True

    def _find_partner_by_vat(self, vat):
        if not vat or len(vat) < 7:
            return self.env["res.partner"]
        Partner = self.env["res.partner"].with_context(active_test=False)
        partners = Partner.search([("vat", "!=", False), ("is_company", "=", True)])
        return partners.filtered(lambda p: _digits(p.vat) == vat)[:1]

    def _ar_responsibility(self, condicion_iva, letter):
        """Responsabilidad AFIP del emisor: por lo impreso ('IVA Responsable Inscripto', 'Monotributo'...) o por la letra."""
        txt = (condicion_iva or "").lower()
        ref = False
        if "inscri" in txt:
            ref = "l10n_ar.res_IVARI"
        elif "monotrib" in txt:
            ref = "l10n_ar.res_RM"
        elif "exent" in txt:
            ref = "l10n_ar.res_IVAE"
        elif letter in ("A", "B", "M"):
            ref = "l10n_ar.res_IVARI"
        elif letter == "C":
            ref = "l10n_ar.res_RM"
        return self.env.ref(ref, raise_if_not_found=False) if ref else self.env["l10n_ar.afip.responsibility.type"]

    def _partner_vals(self, prov, issuer_vat, letter):
        vals = {"name": prov["razon_social"].strip(), "is_company": True, "vat": issuer_vat, "supplier_rank": 1, "company_id": False}
        cuit = self.env.ref("l10n_ar.it_cuit", raise_if_not_found=False)
        if cuit:
            vals["l10n_latam_identification_type_id"] = cuit.id
        resp = self._ar_responsibility(prov.get("condicion_iva"), letter)
        if resp:
            vals["l10n_ar_afip_responsibility_type_id"] = resp.id
        return vals

    def _complete_partner_ar(self, partner, prov, letter):
        """Completa tipo de identificación y responsabilidad AFIP si el proveedor no los tiene (necesarios para la factura)."""
        vals = {}
        cuit = self.env.ref("l10n_ar.it_cuit", raise_if_not_found=False)
        if cuit and partner.l10n_latam_identification_type_id != cuit and len(_digits(partner.vat)) == 11:
            vals["l10n_latam_identification_type_id"] = cuit.id
        if not partner.l10n_ar_afip_responsibility_type_id:
            resp = self._ar_responsibility(prov.get("condicion_iva"), letter)
            if resp:
                vals["l10n_ar_afip_responsibility_type_id"] = resp.id
        if vals:
            partner.write(vals)

    @staticmethod
    def _norm_name(name):
        txt = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().upper()
        txt = re.sub(r"[^A-Z0-9 ]", " ", txt)
        words = [w for w in txt.split() if w not in ("SA", "SRL", "SAS", "SACI", "SACIF", "SACIFI", "SH", "LTDA", "CIA", "Y", "DE", "E", "HNOS", "HERMANOS")]
        return " ".join(words)

    def _find_partner_by_name(self, name, vat):
        """Proveedor existente con la misma razón social (sin CUIT cargado o con el mismo)."""
        key = self._norm_name(name)
        if len(key) < 4:
            return self.env["res.partner"]
        first = key.split()[0]
        Partner = self.env["res.partner"]
        cands = Partner.search([("name", "ilike", first), ("parent_id", "=", False), "|", ("supplier_rank", ">", 0), ("is_company", "=", True)], limit=50)
        for p in cands:
            pk = self._norm_name(p.name)
            if pk and (pk == key or key.startswith(pk + " ") or pk.startswith(key + " ")):
                pv = _digits(p.vat)
                if not pv or pv == vat:
                    if vat and not pv:
                        p.write({"vat": vat})
                    return p
        return Partner

    QUOTE_KEYWORDS = ("PRESUPUESTO", "COTIZ", "PEDIDO", "PROFORMA", "ORDEN")

    def _is_quote(self):
        """Presupuesto, solicitud de pedido, proforma: sirve para la OC pero no es un comprobante fiscal."""
        self.ensure_one()
        tipo = (self.doc_type or "").upper()
        return any(k in tipo for k in self.QUOTE_KEYWORDS) and "FACTURA" not in tipo

    def _apply_result(self, data, info):
        self.ensure_one()
        prov, comp, rec_ = data.get("proveedor") or {}, data.get("comprobante") or {}, data.get("receptor") or {}
        issuer_vat, receiver_vat = _digits(prov.get("cuit")), _digits(rec_.get("cuit"))
        letter = (comp.get("letra") or "").strip().upper()[:1]
        pv, nro = _digits(comp.get("punto_venta")), _digits(comp.get("numero"))
        number = "%s-%s" % (pv.zfill(5), nro.zfill(8)) if pv and nro else (comp.get("numero") or "")
        disc = data.get("descuentos_globales") or []
        charges = data.get("otros_cargos") or []
        perc = data.get("percepciones") or []
        tot = data.get("totales") or {}
        vals = {
            "issuer_name": prov.get("razon_social") or "", "issuer_vat": issuer_vat,
            "receiver_name": rec_.get("razon_social") or "", "receiver_vat": receiver_vat,
            "doc_type": comp.get("tipo") or "", "doc_letter": letter, "doc_number": number,
            "invoice_date": _to_date(comp.get("fecha")), "invoice_date_due": _to_date(comp.get("vencimiento")),
            "cae": comp.get("cae") or "", "cae_due": _to_date(comp.get("cae_vencimiento")),
            "prices_include_tax": letter in ("B", "C"),
            "global_discount_desc": "; ".join("%s %s%s" % (d.get("descripcion") or _("Descuento"), ("%s %%" % d.get("porcentaje")) if _num(d.get("porcentaje")) else "", (" $ %s" % d.get("importe")) if _num(d.get("importe")) else "") for d in disc) or False,
            "other_charges": sum(_num(c.get("importe")) for c in charges),
            "other_charges_desc": "; ".join("%s $ %s" % (c.get("descripcion") or "", c.get("importe")) for c in charges) or False,
            "perceptions_desc": "; ".join("%s $ %s" % (p.get("descripcion") or "", p.get("importe")) for p in perc) or False,
            "amount_untaxed_printed": _num(tot.get("neto_gravado")) + _num(tot.get("neto_no_gravado")) + _num(tot.get("exento")),
            "amount_tax_printed": _num(tot.get("iva")),
            "amount_total_printed": _num(tot.get("total")),
            "ai_notes": data.get("observaciones") or False,
            "ai_model": (info or {}).get("model"), "ai_usage": json.dumps((info or {}).get("usage") or {}),
            "ai_raw": json.dumps(data, ensure_ascii=False, indent=1),
            "reject_reason": False,
        }
        # compañía receptora por CUIT impreso
        if receiver_vat:
            company = self.env["res.company"].search([]).filtered(lambda c: _digits(c.vat) == receiver_vat)[:1]
            if company:
                vals["company_id"] = company.id
        # el emisor no puede ser de la red
        own = self.env["res.company"].search([]).filtered(lambda c: _digits(c.vat) == issuer_vat)
        if issuer_vat and own:
            vals.update({"state": "rejected", "reject_reason": _("El CUIT emisor %s es de %s: no es una factura de compra.", issuer_vat, own[0].name)})
            self.line_ids.unlink()
            self.write(vals)
            return
        if (comp.get("tipo") or "").upper().startswith("REMITO"):
            vals.update({"state": "rejected", "reject_reason": _("Es un remito, no una factura: no se recepciona sin factura.")})
            self.line_ids.unlink()
            self.write(vals)
            return
        partner = self._find_partner_by_vat(issuer_vat)
        if not partner and prov.get("razon_social"):
            # proveedor cargado a mano sin CUIT: lo reconocemos por razón social y le completamos el CUIT
            partner = self._find_partner_by_name(prov["razon_social"], issuer_vat)
        if not partner and issuer_vat and prov.get("razon_social"):
            partner = self.env["res.partner"].create(self._partner_vals(prov, issuer_vat, letter))
            vals["partner_created"] = True
        if partner:
            vals["partner_id"] = partner.id
            partner.supplier_rank = partner.supplier_rank or 1
            self._complete_partner_ar(partner, prov, letter)
        # descuento global: % declarados + importes prorrateados sobre la suma de líneas impresas
        lines = data.get("lineas") or []
        printed_sum = sum(_num(l.get("importe_linea")) or _num(l.get("cantidad")) * _num(l.get("precio_unitario")) * (1 - _num(l.get("descuento_linea_pct")) / 100.0) for l in lines)
        pct = 0.0
        for d in disc:
            if _num(d.get("porcentaje")):
                pct = 100.0 - (100.0 - pct) * (100.0 - _num(d["porcentaje"])) / 100.0
            elif _num(d.get("importe")) and printed_sum:
                pct = 100.0 - (100.0 - pct) * (1.0 - _num(d["importe"]) / printed_sum)
        vals["global_discount_pct"] = pct
        self.line_ids.unlink()
        self.perception_ids.unlink()
        self.write(vals)
        # percepciones impresas → impuestos de la factura de proveedor (no son artículos)
        if not perc and _num(tot.get("percepciones")):
            perc = [{"descripcion": _("Percepciones (sin detalle)"), "importe": _num(tot.get("percepciones"))}]
        Perception = self.env["trx.purchase.inbox.perception"]
        for seq, p in enumerate(perc, start=1):
            if not _num(p.get("importe")):
                continue
            kind, jurisdiction = classify(p.get("descripcion"), p.get("tipo"), p.get("jurisdiccion"))
            guessed, why = False, ""
            if kind == "iibb" and not jurisdiction:
                jurisdiction, why = Perception._guess_jurisdiction(self.partner_id, self.company_id)
                guessed = bool(jurisdiction)
            Perception.create({
                "inbox_id": self.id, "sequence": seq,
                "description": (p.get("descripcion") or "").strip() or dict(KINDS)[kind],
                "kind": kind, "jurisdiction": jurisdiction, "jurisdiction_guessed": guessed,
                "rate": _num(p.get("alicuota")), "base": _num(p.get("base")), "amount": _num(p.get("importe")),
            })
            if guessed:
                self.message_post(body=_("Percepción '%s': la factura no dice la provincia; se tomó %s (%s). Corregila en la pestaña Percepciones si no es esa.",
                                         (p.get("descripcion") or "").strip(), jurisdiction, why))
        self.perception_ids.action_resolve_tax()
        Line = self.env["trx.purchase.inbox.line"]
        for seq, l in enumerate(lines, start=1):
            Line.create({
                "inbox_id": self.id, "sequence": seq,
                "supplier_code": (l.get("codigo_proveedor") or "").strip() or False,
                "ean": _digits(l.get("ean")) if len(_digits(l.get("ean"))) in (8, 12, 13, 14) else False,
                "description": (l.get("descripcion") or "").strip(),
                "qty": _num(l.get("cantidad")) or 1.0,
                "uom_text": l.get("unidad") or False,
                "price_printed": _num(l.get("precio_unitario")),
                "discount_line_pct": _num(l.get("descuento_linea_pct")),
                "amount_printed": _num(l.get("importe_linea")),
                "tax_rate": _num(l.get("alicuota_iva")) if l.get("alicuota_iva") not in (None, "") else (21.0),
                "extra": l.get("extra") or False,
                "source_text": l.get("texto_original") or False,
            })
        self.line_ids._match_products()
        self.line_ids._snapshot_current()
        self.non_fiscal = self._is_quote() or (not self.doc_letter and not self.cae)
        self.state = "review" if (self.count_new or not self.totals_ok) else "scanned"
        if self.non_fiscal:
            self.message_post(body=_("Comprobante no fiscal (%s): la orden de compra y la factura van sin IVA y la factura se registra en el diario de compras NF, sin documento ni ARCA.", self.doc_type or "-"))
        self.message_post(body=_(
            "Factura leída (%s): %s líneas, %s reconocidas, %s a resolver; descuento global %s %%; total impreso %s, calculado %s (diferencia %s).",
            self.ai_model or "", self.line_count, self.count_matched, self.count_new, round(self.global_discount_pct, 2),
            self.amount_total_printed, round(self.amount_total_calc, 2), round(self.amount_diff, 2),
        ))

    # ---------------------------------------------------------------- acciones
    def action_create_products(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.match_state != "matched")
        lines.action_create_product()
        self._publish_pos(lines.product_id.product_tmpl_id)
        return True

    def _publish_pos(self, templates=None):
        """Activa los artículos de la factura para el POS (activo, vendible, disponible en POS) y los publica
        en los puntos de venta con sesión abierta: aparecen en la caja sin recargar."""
        self.ensure_one()
        templates = templates if templates is not None else self.line_ids.product_id.product_tmpl_id
        if not templates:
            return 0, 0
        templates = templates.with_context(active_test=False)
        to_activate = templates.filtered(lambda t: not (t.active and t.sale_ok and t.available_in_pos))
        if to_activate:
            # available_in_pos va en los valores: trx_pos_price_sync lo detecta y avisa a las cajas abiertas
            to_activate.write({"active": True, "sale_ok": True, "available_in_pos": True})
        activated = len(to_activate)
        # el resto (ya activos) también se reenvía, por si la caja abrió antes de crearlos o cambió el precio
        _register_for_sync(self.env, "product.template", (templates - to_activate).ids)
        notified = self.env["pos.session"].sudo().search_count([("state", "=", "opened")])
        self.message_post(body=_("Publicados en el POS: %(n)s artículo(s)%(act)s; avisados %(pos)s punto(s) de venta abiertos.",
                                 n=len(templates), act=_(" (%s activado/s)", activated) if activated else "", pos=notified))
        return activated, notified

    def action_publish_pos(self):
        self.ensure_one()
        if not self.line_ids.product_id:
            raise UserError(_("Todavía no hay artículos asociados a las líneas."))
        activated, notified = self._publish_pos()
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Publicado en el POS"), "type": "success", "sticky": False,
            "message": _("%(n)s artículo(s) disponibles en el POS; %(pos)s punto(s) de venta abiertos actualizados.",
                         n=len(self.line_ids.product_id.product_tmpl_id), pos=notified),
        }}

    def _find_purchase_tax(self, rate):
        """IVA de compras con esa alícuota: por grupo de impuestos con código AFIP de IVA (independiente del idioma)."""
        Tax = self.env["account.tax"]
        base = [("company_id", "=", self.company_id.id), ("type_tax_use", "=", "purchase"), ("amount_type", "=", "percent"), ("amount", "=", rate)]
        for extra in ([("tax_group_id.l10n_ar_vat_afip_code", "!=", False)], ["|", ("name", "ilike", "IVA"), ("name", "ilike", "VAT")], []):
            tax = Tax.search(base + extra + [("price_include_override", "!=", "tax_included")], limit=1) or Tax.search(base + extra, limit=1)
            if tax:
                return tax
        return Tax

    def action_create_po(self):
        self.ensure_one()
        if self.state in ("done", "rejected"):
            raise UserError(_("Esta factura ya fue procesada o está rechazada."))
        if not self.partner_id:
            raise UserError(_("Falta el proveedor: elegilo o corregí el CUIT."))
        unresolved = self.line_ids.filtered(lambda l: l.match_state != "matched" or not l.product_id)
        if unresolved:
            raise UserError(_("Hay %s líneas sin artículo. Elegí el artículo o usá 'Incorporar' para crearlos.", len(unresolved)))
        company = self.company_id
        PO = self.env["purchase.order"].with_company(company)
        ref = ("%s%s %s %s" % ("NF " if self.non_fiscal else "", self.doc_type or "FACTURA", self.doc_letter or "", self.doc_number or "")).strip()
        ref = re.sub(r"\s+", " ", ref)
        if ref and PO.search_count([("partner_ref", "=", ref), ("partner_id", "=", self.partner_id.id), ("company_id", "=", company.id)]):
            raise UserError(_("Ya existe una orden de compra con la referencia %s para este proveedor.", ref))
        lines_vals = []
        for l in self.line_ids:
            tax = self.env["account.tax"] if self.non_fiscal else self._find_purchase_tax(l.tax_rate)
            lines_vals.append((0, 0, {
                "product_id": l.product_id.id,
                "name": "[%s] %s" % (l.supplier_code, l.description) if l.supplier_code else l.description,
                "product_qty": l.qty,
                "price_unit": l.price_net_untaxed,
                "tax_ids": [(6, 0, tax.ids)] if tax else False,
                "date_planned": fields.Datetime.now(),
            }))
        if self.picking_type_id and self.picking_type_id.company_id != company:
            raise UserError(_("El local de recepción %s no es de %s.", self.picking_type_id.display_name, company.name))
        po_extra = {"picking_type_id": self.picking_type_id.id} if self.picking_type_id else {}
        po = PO.create({
            **po_extra,
            "partner_id": self.partner_id.id,
            "company_id": company.id,
            "partner_ref": ref,
            "origin": self.name,
            "date_order": fields.Datetime.now(),
            "currency_id": company.currency_id.id,
            "note": _("Generada por lectura automática de la factura %s (%s). Costo neto = precio impreso − descuentos (línea y global %s %%).",
                      self.doc_number or "", self.file_name or "", round(self.global_discount_pct, 2)),
            "order_line": lines_vals,
        })
        self.purchase_id = po
        po.message_post(body=_("Origen: factura escaneada %s. Total impreso %s, calculado %s.", self.name, self.amount_total_printed, round(self.amount_total_calc, 2)))
        if self.totals_ok:
            po.button_confirm()
            self._update_supplier_prices()
            self.state = "done"
            self.message_post(body=_("Orden de compra %s confirmada: la recepción queda pendiente en %s.", po.name, ", ".join(po.picking_ids.mapped("name")) or "-"))
        else:
            self.state = "review"
            po.activity_schedule("mail.mail_activity_data_todo", summary=_("Revisar factura %s: los totales no cierran (diferencia %s)", self.doc_number, round(self.amount_diff, 2)), user_id=self.env.uid)
            self.message_post(body=_("Orden de compra %s en borrador: los totales no cierran (diferencia %s). Revisá y confirmá a mano.", po.name, round(self.amount_diff, 2)))
        self._publish_pos()
        for l in self.line_ids.filtered("price_up"):
            po.message_post(body=_("Aviso: %s vino a %s, %s %% sobre el último costo (%s).", l.product_id.display_name, round(l.price_net_untaxed, 2), round(l.price_up_pct * 100, 1), round(l.cost_current, 2)))
        return self.action_view_po()

    def _update_supplier_prices(self):
        """Último precio pagado → línea de proveedor del artículo (historial con origen Factura)."""
        self.ensure_one()
        ctx = {"trx_price_history_origin": "invoice", "trx_price_history_ref": "%s %s" % (self.name, self.doc_number or ""),
               "trx_price_history_reason": _("Factura %s de %s", self.doc_number or "", self.partner_id.name)}
        Seller = self.env["product.supplierinfo"].with_context(**ctx)
        prec = self.env["decimal.precision"].precision_get("Product Price")
        for l in self.line_ids.filtered("product_id"):
            tmpl = l.product_id.product_tmpl_id
            seller = Seller.search([("partner_id", "=", self.partner_id.id), ("product_tmpl_id", "=", tmpl.id), ("company_id", "=", False)], order="sequence, id", limit=1) \
                or Seller.search([("partner_id", "=", self.partner_id.id), ("product_tmpl_id", "=", tmpl.id)], order="sequence, id", limit=1)
            vals = {"price": l.price_net_untaxed, "discount": 0.0, "replenishment_cost_rule_id": False, "date_start": self.invoice_date or fields.Date.context_today(self)}
            if l.supplier_code:
                vals["product_code"] = l.supplier_code
            if seller:
                if float_compare(seller.net_price * (1 - (seller.discount or 0) / 100.0), l.price_net_untaxed, precision_digits=prec) != 0 or seller.replenishment_cost_rule_id or seller.discount:
                    seller.write(vals)
            else:
                vals.update({"partner_id": self.partner_id.id, "product_tmpl_id": tmpl.id, "company_id": False, "min_qty": 0, "product_name": l.description})
                Seller.create(vals)
            if tmpl.replenishment_cost_type == "manual" and float_is_zero(tmpl.replenishment_base_cost, precision_digits=prec):
                tmpl.with_context(**ctx).write({"replenishment_cost_type": "supplier_price"})
        return True

    # ------------------------------------------------- factura de proveedor
    def _find_document_type(self, journal):
        """Tipo de comprobante l10n_ar según letra y tipo impreso (Factura A → código 1, B → 6, C → 11...)."""
        self.ensure_one()
        DocType = self.env["l10n_latam.document.type"]
        letter = (self.doc_letter or "A").upper()
        is_credit = (self.doc_type or "").upper().startswith("NOTA DE CR") or (self.doc_type or "").upper().startswith("NC")
        code = (CREDIT_NOTE_DOC_CODES if is_credit else INVOICE_DOC_CODES).get(letter)
        domain = [("country_id.code", "=", "AR")]
        doc = DocType.search(domain + [("code", "=", code)], limit=1) if code else DocType
        if not doc:
            doc = DocType.search(domain + [("l10n_ar_letter", "=", letter), ("internal_type", "=", "credit_note" if is_credit else "invoice")], limit=1)
        return doc, is_credit

    def action_create_bill(self):
        """Factura de proveedor en borrador, vinculada a la orden de compra, con las percepciones como impuestos
        (importe fijo = el impreso). No se valida: Administración la revisa contra el papel y la confirma."""
        self.ensure_one()
        if self.invoice_id:
            return self.action_view_bill()
        po = self.purchase_id
        if not po:
            raise UserError(_("Primero generá la orden de compra."))
        if po.state not in ("purchase", "done"):
            raise UserError(_("La orden de compra %s está en borrador: confirmala antes de cargar la factura.", po.name))
        missing = self.perception_ids.filtered(lambda p: not p.tax_id)
        if missing:
            missing.action_resolve_tax()
            missing = self.perception_ids.filtered(lambda p: not p.tax_id)
            if missing:
                raise UserError(_("No encuentro impuesto para: %s. Elegilo a mano en la pestaña Percepciones.", ", ".join(missing.mapped("description"))))
        company = self.company_id
        Move = self.env["account.move"].with_company(company)
        if self.non_fiscal:
            journal = self._get_nf_purchase_journal(company)
        else:
            journal = self.env["account.journal"].search([("company_id", "=", company.id), ("type", "=", "purchase"), ("l10n_latam_use_documents", "=", True)], limit=1) \
                or self.env["account.journal"].search([("company_id", "=", company.id), ("type", "=", "purchase")], limit=1)
        if not journal:
            raise UserError(_("La compañía %s no tiene diario de compras.", company.name))
        doc_type, is_credit = self._find_document_type(journal)
        if self.non_fiscal:
            doc_type = self.env["l10n_latam.document.type"]
            dup = Move.search([("journal_id", "=", journal.id), ("partner_id", "=", self.partner_id.commercial_partner_id.id), ("ref", "=", po.partner_ref)], limit=1) if po.partner_ref else Move
            if dup:
                raise UserError(_("Ya existe la factura no fiscal %s de este proveedor: %s.", po.partner_ref, dup.display_name))
        if not self.non_fiscal and self.doc_number and journal.l10n_latam_use_documents and doc_type:
            dup = Move.search([("partner_id", "=", self.partner_id.commercial_partner_id.id), ("company_id", "=", company.id), ("move_type", "in", ("in_invoice", "in_refund")),
                               ("l10n_latam_document_type_id", "=", doc_type.id), ("name", "=like", "%" + self.doc_number)], limit=1)
            if dup:
                raise UserError(_("Ya existe la factura %s de este proveedor: %s.", self.doc_number, dup.display_name))
        lines_vals = []
        for pl in po.order_line.filtered(lambda l: l.product_id and not l.display_type):
            lines_vals.append((0, 0, {
                "product_id": pl.product_id.id, "name": pl.name, "quantity": pl.product_qty, "product_uom_id": pl.product_uom_id.id,
                "price_unit": pl.price_unit, "tax_ids": [(6, 0, pl.tax_ids.ids)], "purchase_line_id": pl.id,
            }))
        vals = {
            "move_type": "in_refund" if is_credit else "in_invoice",
            "company_id": company.id, "journal_id": journal.id, "currency_id": po.currency_id.id,
            "partner_id": self.partner_id.id, "invoice_date": self.invoice_date or fields.Date.context_today(self),
            "invoice_date_due": self.invoice_date_due or False, "invoice_origin": po.name, "ref": po.partner_ref,
            "invoice_line_ids": lines_vals,
        }
        if doc_type and journal.l10n_latam_use_documents:
            vals["l10n_latam_document_type_id"] = doc_type.id
            if self.doc_number:
                vals["l10n_latam_document_number"] = self.doc_number
        move = Move.create(vals)
        if not move.invoice_date_due:
            move._compute_invoice_date_due()
        if not self.non_fiscal:
            self._apply_perceptions(move)
        self.invoice_id = move
        move.message_post(body=_("Generada desde la factura escaneada %s (archivo %s). Percepciones: %s. Total impreso %s, factura %s.",
                                 self.name, self.file_name or "", "; ".join("%s $ %s" % (p.tax_id.name, p.amount) for p in self.perception_ids) or "-",
                                 self.amount_total_printed, round(move.amount_total, 2)))
        diff = round(move.amount_total - (self.amount_total_printed or 0.0), 2)
        if abs(diff) > max(1.0, (self.amount_total_printed or 0.0) * 0.005):
            move.activity_schedule("mail.mail_activity_data_todo", user_id=self.env.uid,
                                   summary=_("Factura %s: el total %s no coincide con el impreso %s (diferencia %s)", self.doc_number, round(move.amount_total, 2), self.amount_total_printed, diff))
        self.message_post(body=_("Factura de proveedor %s en borrador (total %s, impreso %s). Percepciones cargadas como impuestos: %s.",
                                 move.display_name, round(move.amount_total, 2), self.amount_total_printed,
                                 ", ".join("%s $ %s" % (p.tax_id.name, p.amount) for p in self.perception_ids) or "ninguna"))
        return self.action_view_bill()

    def _get_nf_purchase_journal(self, company):
        """Diario de compras no fiscal (NF): no maneja documentos, así no se asocia a tipos de comprobante ni a ARCA.
        Si no existe se crea, con la misma cuenta por defecto que el diario de compras fiscal."""
        Journal = self.env["account.journal"].sudo().with_company(company)
        domain = [("company_id", "=", company.id), ("type", "=", "purchase"), ("l10n_latam_use_documents", "=", False)]
        journal = Journal.search(domain + [("code", "=", "NF")], limit=1) or Journal.search(domain, order="id", limit=1)
        if journal:
            return journal
        fiscal = Journal.search([("company_id", "=", company.id), ("type", "=", "purchase")], order="id", limit=1)
        codes = set(Journal.with_context(active_test=False).search([("company_id", "=", company.id)]).mapped("code"))
        code = next(c for c in ("NF", "CNF", "NFC", "NF2", "NF3") if c not in codes)
        journal = Journal.create({
            "name": _("Compras NF (no fiscal)"), "code": code, "type": "purchase", "company_id": company.id,
            "l10n_latam_use_documents": False,
            "default_account_id": fiscal.default_account_id.id if fiscal.default_account_id else False,
        })
        self.message_post(body=_("Se creó el diario de compras no fiscal %s (%s), sin documentos ni ARCA.", journal.name, journal.code))
        return journal

    def _apply_perceptions(self, move):
        """Agrega cada impuesto de percepción a la primera línea y fija el importe impreso en el apunte del impuesto
        (mismo mecanismo que editar el importe en el widget de totales de la factura)."""
        self.ensure_one()
        base_line = move.invoice_line_ids.filtered(lambda l: l.display_type == "product")[:1]
        if not base_line or not self.perception_ids:
            return
        sign = 1 if move.is_outbound() else -1
        perceptions = self.perception_ids.filtered("tax_id")
        # primero todos los impuestos (cada cambio en la línea base recalcula los apuntes de impuesto), después los importes
        new_taxes = perceptions.mapped("tax_id") - base_line.tax_ids
        if new_taxes:
            base_line.write({"tax_ids": [(4, t.id) for t in new_taxes]})
        for p in perceptions:
            tax = p.tax_id
            tax_lines = move.line_ids.filtered(lambda l: l.tax_line_id == tax)
            if not tax_lines:
                raise UserError(_("No se pudo generar el apunte del impuesto %s en la factura.", tax.name))
            first = tax_lines[0]
            current = sum(tax_lines.mapped("amount_currency")) * sign
            delta = p.amount - current
            if not move.currency_id.is_zero(delta):
                first.write({"amount_currency": first.amount_currency + delta * sign})
        move._compute_amount()

    def action_view_bill(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "account.move", "res_id": self.invoice_id.id, "view_mode": "form", "target": "current"}

    def action_view_po(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "purchase.order", "res_id": self.purchase_id.id, "view_mode": "form", "target": "current"}

    def action_view_pickings(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.action_picking_tree_all")
        action["domain"] = [("id", "in", self.purchase_id.picking_ids.ids)]
        return action

    def action_reset(self):
        for rec in self:
            if rec.state == "done":
                raise UserError(_("Ya generó una orden de compra."))
            rec.write({"state": "draft", "reject_reason": False})
        return True

    def action_reject(self):
        for rec in self:
            if rec.state == "done":
                raise UserError(_("Ya generó una orden de compra."))
            rec.write({"state": "rejected", "reject_reason": rec.reject_reason or _("Rechazada a mano.")})
        return True
