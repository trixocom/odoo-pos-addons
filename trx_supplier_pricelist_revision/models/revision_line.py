# Part of trx_supplier_pricelist_revision. Author: Trixocom. License: LGPL-3.
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

MATCH_STATES = [
    ("matched", "Coincide"),
    ("suggested", "Sugerido (confirmar)"),
    ("new", "Nuevo"),
    ("unresolved", "Sin resolver"),
]
MATCH_BY = [
    ("barcode", "Código de barras"),
    ("supplier_code", "Código del proveedor"),
    ("default_code", "Código alfa"),
    ("name", "Nombre"),
    ("manual", "Elegido a mano"),
    ("created", "Incorporado"),
]
TRENDS = [
    ("up", "Subió"),
    ("down", "Bajó"),
    ("equal", "Igual"),
    ("new", "Nuevo / sin costo"),
]
DECISIONS = [
    ("apply", "Aplicar costo y PVP"),
    ("keep_pvp", "Aplicar costo, mantener PVP"),
    ("skip", "No incorporar"),
]
LINE_STATES = [
    ("pending", "Pendiente"),
    ("applied", "Aplicada"),
    ("skipped", "No incorporada"),
]


class TrxSupplierPricelistRevisionLine(models.Model):
    _name = "trx.supplier.pricelist.revision.line"
    _description = "Línea de lista de proveedor"
    _order = "revision_id desc, sequence, id"

    revision_id = fields.Many2one("trx.supplier.pricelist.revision", string="Lista", required=True, ondelete="cascade", index=True)
    partner_id = fields.Many2one(related="revision_id.partner_id", store=True, index=True)
    revision_state = fields.Selection(related="revision_id.state")
    currency_id = fields.Many2one(related="revision_id.currency_id")
    sequence = fields.Integer(default=10)
    supplier_code = fields.Char(string="Código prov.", index=True)
    supplier_name = fields.Char(string="Descripción del proveedor")
    barcode = fields.Char(string="Código de barras")
    list_price = fields.Monetary(string="Precio de lista", currency_field="currency_id")
    discount_pct = fields.Float(string="Bonif. %", digits="Discount")
    net_cost = fields.Monetary(string="Costo nuevo", currency_field="currency_id", compute="_compute_net_cost", store=True)
    suggested_pvp = fields.Monetary(string="PVP sugerido prov.", currency_field="currency_id")

    product_tmpl_id = fields.Many2one("product.template", string="Artículo", index=True, ondelete="set null")
    default_code = fields.Char(related="product_tmpl_id.default_code", string="Código alfa")
    match_state = fields.Selection(MATCH_STATES, string="Reconocimiento", default="new", required=True, index=True)
    match_by = fields.Selection(MATCH_BY, string="Reconocido por")
    match_note = fields.Char(string="Observación")

    cost_current = fields.Monetary(string="Costo actual", currency_field="currency_id",
                                   help="Costo neto vigente con este proveedor al momento de cargar la lista.")
    cost_var_pct = fields.Float(string="Var. costo", compute="_compute_variations", store=True, digits=(16, 4))
    trend = fields.Selection(TRENDS, string="Tendencia", compute="_compute_variations", store=True, index=True)
    pvp_current = fields.Monetary(string="PVP actual", currency_field="currency_id")
    pvp_proposed = fields.Monetary(string="PVP propuesto", currency_field="currency_id")
    pvp_manual = fields.Boolean(string="PVP editado a mano", default=False)
    pvp_var_pct = fields.Float(string="Var. PVP", compute="_compute_variations", store=True, digits=(16, 4))
    pvp_previous = fields.Monetary(string="PVP anterior", currency_field="currency_id", compute="_compute_pvp_previous",
                                   help="PVP que tenía el artículo antes del último cambio (historial de precios).")
    decision = fields.Selection(DECISIONS, string="Decisión", default="skip", required=True, index=True)
    state = fields.Selection(LINE_STATES, string="Estado", default="pending", required=True, copy=False)
    supplierinfo_id = fields.Many2one("product.supplierinfo", string="Línea de proveedor aplicada", readonly=True, copy=False)

    @api.depends("list_price", "discount_pct")
    def _compute_net_cost(self):
        for line in self:
            line.net_cost = line.list_price * (1.0 - (line.discount_pct or 0.0) / 100.0)

    @api.depends("net_cost", "cost_current", "pvp_current", "pvp_proposed", "match_state", "product_tmpl_id")
    def _compute_variations(self):
        prec = self.env["decimal.precision"].precision_get("Product Price")
        for line in self:
            if line.match_state != "matched" or not line.product_tmpl_id or float_is_zero(line.cost_current, precision_digits=prec):
                line.trend = "new"
                line.cost_var_pct = 0.0
            else:
                line.cost_var_pct = (line.net_cost - line.cost_current) / line.cost_current
                cmp_ = float_compare(line.net_cost, line.cost_current, precision_digits=prec)
                line.trend = "up" if cmp_ > 0 else ("down" if cmp_ < 0 else "equal")
            line.pvp_var_pct = ((line.pvp_proposed - line.pvp_current) / line.pvp_current) if line.pvp_current else 0.0

    @api.depends("product_tmpl_id")
    def _compute_pvp_previous(self):
        for line in self:
            line.pvp_previous = line.product_tmpl_id.trx_pvp_previous if line.product_tmpl_id else 0.0

    @api.onchange("pvp_proposed")
    def _onchange_pvp_proposed(self):
        self.pvp_manual = True

    @api.onchange("product_tmpl_id")
    def _onchange_product_tmpl_id(self):
        if self.product_tmpl_id:
            self.match_state = "matched"
            self.match_by = "manual"
            self.match_note = False
        else:
            self.match_state = "new"
            self.match_by = False

    def write(self, vals):
        res = super().write(vals)
        if "product_tmpl_id" in vals and not self.env.context.get("trx_revision_internal"):
            # elegido a mano: tomar valores actuales y proponer PVP
            self._snapshot_current()
            self._compute_proposals(force=False)
        return res

    # ------------------------------------------------------------ reconocer
    def _find_product(self):
        """Busca el artículo por: código de barras → código del proveedor → código alfa → nombre (sugerido)."""
        self.ensure_one()
        Product = self.env["product.product"].with_context(active_test=False)
        Tmpl = self.env["product.template"].with_context(active_test=False)
        Seller = self.env["product.supplierinfo"]
        partner = self.revision_id.partner_id
        if self.barcode:
            prod = Product.search([("barcode", "=", self.barcode)], limit=1)
            if prod:
                return prod.product_tmpl_id, "matched", "barcode"
        if self.supplier_code:
            seller = Seller.search([("partner_id", "=", partner.id), ("product_code", "=", self.supplier_code)], limit=1)
            if seller:
                return seller.product_tmpl_id or seller.product_id.product_tmpl_id, "matched", "supplier_code"
            tmpl = Tmpl.search([("default_code", "=", self.supplier_code)], limit=1)
            if tmpl:
                return tmpl, "matched", "default_code"
        if self.supplier_name and len(self.supplier_name) >= 6:
            tmpl = Tmpl.search([("name", "=ilike", self.supplier_name.strip())], limit=1)
            if tmpl:
                return tmpl, "suggested", "name"
        return Tmpl, "new", False

    def _match_products(self):
        seen = {}
        for line in self.sorted(lambda l: (l.sequence, l.id)):
            if line.match_by in ("manual", "created") and line.product_tmpl_id:
                seen.setdefault(line.product_tmpl_id.id, line)
                continue
            tmpl, state, by = line._find_product()
            note = False
            if tmpl and state == "matched" and tmpl.id in seen:
                state, note = "unresolved", _("Mismo artículo que la línea con código %s", seen[tmpl.id].supplier_code)
            elif tmpl and state == "matched":
                seen[tmpl.id] = line
            line.with_context(trx_revision_internal=True).write({
                "product_tmpl_id": tmpl.id if tmpl else False,
                "match_state": state,
                "match_by": by or False,
                "match_note": note,
            })
        return True

    # ------------------------------------------------------------- valores
    def _current_seller(self):
        self.ensure_one()
        Seller = self.env["product.supplierinfo"]
        partner = self.revision_id.partner_id
        tmpl = self.product_tmpl_id
        if not tmpl:
            return Seller
        return Seller.search(
            [("partner_id", "=", partner.id), ("product_tmpl_id", "=", tmpl.id), ("company_id", "=", False)],
            order="sequence, id", limit=1,
        ) or Seller.search(
            [("partner_id", "=", partner.id), ("product_tmpl_id", "=", tmpl.id)], order="sequence, id", limit=1,
        )

    def _snapshot_current(self):
        for line in self:
            tmpl = line.product_tmpl_id
            vals = {"cost_current": 0.0, "pvp_current": 0.0}
            if tmpl and line.match_state in ("matched", "suggested", "unresolved"):
                seller = line._current_seller()
                if seller:
                    vals["cost_current"] = seller.net_price * (1.0 - (seller.discount or 0.0) / 100.0)
                vals["pvp_current"] = tmpl.list_price
            line.with_context(trx_revision_internal=True).write(vals)
        return True

    def _round_pvp(self, value):
        self.ensure_one()
        step = float(self.revision_id.pvp_rounding or "0")
        if step <= 0 or not value:
            return value
        return round(value / step) * step

    def _pvp_by_margin(self, tmpl, net_cost):
        base = net_cost * (1.0 + (tmpl.sale_margin or 0.0) / 100.0) + (tmpl.sale_surcharge or 0.0)
        company = tmpl.company_id or self.env.company
        taxes = tmpl.taxes_id.filtered_domain(self.env["account.tax"]._check_company_domain(company))
        inc_taxes = taxes.filtered("price_include")
        if inc_taxes:
            base = inc_taxes.compute_all(base, tmpl.currency_id, product=tmpl, handle_price_include=False)["total_included"]
        return base

    def _propose_pvp(self):
        """PVP propuesto según la regla del documento (sin redondear la decisión de bajas)."""
        self.ensure_one()
        rev = self.revision_id
        rule = rev.pvp_rule
        tmpl = self.product_tmpl_id
        if rule == "list_factor":
            value = self.list_price * (rev.pvp_factor or 0.0)
        elif rule == "cost_factor":
            value = self.net_cost * (rev.pvp_factor or 0.0)
        elif rule == "suggested":
            value = self.suggested_pvp or self.pvp_current
        elif rule == "margin":
            value = self._pvp_by_margin(tmpl, self.net_cost) if tmpl and tmpl.list_price_type == "by_margin" else self.pvp_current
        else:  # keep
            value = self.pvp_current
        return self._round_pvp(value)

    def _compute_proposals(self, force=False):
        prec = self.env["decimal.precision"].precision_get("Product Price")
        for line in self:
            rev = line.revision_id
            vals = {}
            if line.match_state != "matched" or not line.product_tmpl_id:
                vals["decision"] = "skip"
                if force or not line.pvp_manual:
                    vals["pvp_proposed"] = line._propose_pvp()
                    vals["pvp_manual"] = False
            else:
                is_down = float_compare(line.net_cost, line.cost_current, precision_digits=prec) < 0 and not float_is_zero(line.cost_current, precision_digits=prec)
                if is_down and rev.keep_pvp_on_decrease:
                    vals["decision"] = "keep_pvp"
                    if force or not line.pvp_manual:
                        vals["pvp_proposed"] = line.pvp_current
                        vals["pvp_manual"] = False
                else:
                    vals["decision"] = "apply"
                    if force or not line.pvp_manual:
                        vals["pvp_proposed"] = line._propose_pvp()
                        vals["pvp_manual"] = False
            line.with_context(trx_revision_internal=True).write(vals)
        return True

    # ------------------------------------------------------------- acciones
    def _check_editable(self):
        if any(l.revision_id.state not in ("draft", "review") for l in self):
            raise UserError(_("La lista ya no está en revisión."))

    def action_set_apply(self):
        self._check_editable()
        self.filtered(lambda l: l.match_state == "matched").write({"decision": "apply"})
        return True

    def action_set_keep_pvp(self):
        self._check_editable()
        self.filtered(lambda l: l.match_state == "matched").write({"decision": "keep_pvp"})
        return True

    def action_set_skip(self):
        self._check_editable()
        self.write({"decision": "skip"})
        return True

    def action_lower_pvp(self):
        """Para las líneas que bajaron: proponer el PVP por la regla y aplicarlo (baja el PVP)."""
        self._check_editable()
        for line in self.filtered(lambda l: l.match_state == "matched"):
            line.with_context(trx_revision_internal=True).write({
                "pvp_proposed": line._propose_pvp(), "pvp_manual": False, "decision": "apply",
            })
        return True

    def action_recompute_pvp(self):
        self._check_editable()
        for line in self:
            line.with_context(trx_revision_internal=True).write({"pvp_proposed": line._propose_pvp(), "pvp_manual": False})
        return True

    def action_confirm_suggested(self):
        self._check_editable()
        for line in self.filtered(lambda l: l.match_state in ("suggested", "unresolved") and l.product_tmpl_id):
            line.with_context(trx_revision_internal=True).write({"match_state": "matched", "match_by": "manual", "match_note": False})
            line._snapshot_current()
            line._compute_proposals(force=False)
        return True

    def action_create_product(self):
        """Incorporar: crea el artículo (código alfa automático del proveedor) con su línea de proveedor."""
        self._check_editable()
        Tmpl = self.env["product.template"]
        Product = self.env["product.product"].with_context(active_test=False)
        created = self.env["product.template"]
        for line in self:
            if line.product_tmpl_id and line.match_state == "matched":
                continue
            rev = line.revision_id
            partner = rev.partner_id
            if not line.supplier_name:
                raise UserError(_("La línea con código %s no tiene descripción: no se puede crear el artículo.", line.supplier_code))
            barcode = line.barcode or False
            if barcode and Product.search_count([("barcode", "=", barcode)]):
                barcode = False
            code = partner._trx_next_alfa()
            rule = rev._get_discount_rule(line.discount_pct)
            pvp = line.pvp_proposed or line._propose_pvp()
            vals = {
                "name": line.supplier_name.strip(),
                "default_code": code,
                "barcode": barcode,
                "type": "consu",
                "is_storable": True,
                "sale_ok": True,
                "purchase_ok": True,
                "company_id": False,
                "list_price": pvp or 0.0,
                "replenishment_cost_type": "supplier_price",
                "seller_ids": [(0, 0, {
                    "partner_id": partner.id,
                    "product_code": line.supplier_code or False,
                    "product_name": line.supplier_name.strip(),
                    "price": line.list_price,
                    "discount": 0.0,
                    "replenishment_cost_rule_id": rule.id or False,
                    "min_qty": 0,
                    "company_id": False,
                    "date_start": fields.Date.context_today(line),
                })],
            }
            if "available_in_pos" in Tmpl._fields:
                vals["available_in_pos"] = True
            tmpl = Tmpl.with_context(**rev._history_context()).create(vals)
            created |= tmpl
            line.with_context(trx_revision_internal=True).write({
                "product_tmpl_id": tmpl.id, "match_state": "matched", "match_by": "created", "match_note": False,
                "cost_current": line.net_cost, "pvp_current": tmpl.list_price, "pvp_proposed": tmpl.list_price,
                "decision": "apply",
            })
        if created:
            self[0].revision_id.message_post(body=_(
                "Artículos incorporados: %s", ", ".join("%s %s" % (t.default_code, t.name) for t in created)
            ))
        return True

    def action_open_product(self):
        self.ensure_one()
        if not self.product_tmpl_id:
            raise UserError(_("La línea no tiene artículo."))
        return {
            "type": "ir.actions.act_window", "res_model": "product.template", "res_id": self.product_tmpl_id.id,
            "view_mode": "form", "target": "current",
        }
