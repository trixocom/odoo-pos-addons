# Part of trx_purchase_ai_inbox. Author: Trixocom. License: LGPL-3.
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

MATCH_STATES = [
    ("matched", "Coincide"),
    ("suggested", "Sugerido (confirmar)"),
    ("new", "Nuevo"),
]
MATCH_BY = [
    ("ean", "Código de barras"),
    ("supplier_code", "Código del proveedor"),
    ("default_code", "Código alfa"),
    ("name", "Descripción"),
    ("manual", "Elegido a mano"),
    ("created", "Incorporado"),
]


def _ean_valid(code):
    if not code or not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    check = digits.pop()
    total = sum(d * (3 if (len(digits) - i) % 2 == 1 else 1) for i, d in enumerate(digits))
    return (10 - total % 10) % 10 == check


class TrxPurchaseInboxLine(models.Model):
    _name = "trx.purchase.inbox.line"
    _description = "Línea de factura de proveedor escaneada"
    _order = "inbox_id desc, sequence, id"

    inbox_id = fields.Many2one("trx.purchase.inbox", required=True, ondelete="cascade", index=True)
    inbox_state = fields.Selection(related="inbox_id.state")
    partner_id = fields.Many2one(related="inbox_id.partner_id", store=True)
    currency_id = fields.Many2one(related="inbox_id.currency_id")
    sequence = fields.Integer(default=10)
    supplier_code = fields.Char(string="Código prov.")
    ean = fields.Char(string="EAN")
    ean_valid = fields.Boolean(compute="_compute_ean_valid")
    description = fields.Char(string="Descripción", required=True)
    qty = fields.Float(string="Cantidad", digits="Product Unit of Measure", default=1.0)
    uom_text = fields.Char(string="Unidad")
    price_printed = fields.Monetary(string="Precio impreso", currency_field="currency_id")
    discount_line_pct = fields.Float(string="Dto. línea %", digits="Discount")
    amount_printed = fields.Monetary(string="Importe impreso", currency_field="currency_id")
    tax_rate = fields.Float(string="IVA %", digits=(16, 2), default=21.0)
    price_net = fields.Monetary(string="Costo neto (c/dto.)", currency_field="currency_id", compute="_compute_price_net", store=True,
                                help="Precio impreso − descuento de línea − descuento global prorrateado (en la moneda de la factura, con IVA si es B/C).")
    price_net_untaxed = fields.Monetary(string="Costo neto sin IVA", currency_field="currency_id", compute="_compute_price_net", store=True,
                                        help="El costo real por unidad que va a la OC y a la ficha del artículo.")
    product_id = fields.Many2one("product.product", string="Artículo", index=True)
    default_code = fields.Char(related="product_id.default_code", string="Alfa")
    match_state = fields.Selection(MATCH_STATES, default="new", required=True, index=True)
    match_by = fields.Selection(MATCH_BY)
    cost_current = fields.Monetary(string="Último costo", currency_field="currency_id", readonly=True)
    price_up = fields.Boolean(string="Subió", compute="_compute_price_up", store=True)
    price_up_pct = fields.Float(string="Var. costo", compute="_compute_price_up", store=True, digits=(16, 4))
    extra = fields.Char(string="Otros datos")
    source_text = fields.Char(string="Texto original")

    @api.depends("ean")
    def _compute_ean_valid(self):
        for l in self:
            l.ean_valid = _ean_valid(l.ean or "")

    @api.depends("price_printed", "discount_line_pct", "inbox_id.global_discount_pct", "inbox_id.prices_include_tax", "tax_rate",
                 "inbox_id.non_fiscal", "inbox_id.amount_tax_printed")
    def _compute_price_net(self):
        for l in self:
            inbox = l.inbox_id
            net = (l.price_printed or 0.0) * (1 - (l.discount_line_pct or 0.0) / 100.0) * (1 - (inbox.global_discount_pct or 0.0) / 100.0)
            l.price_net = net
            if inbox.non_fiscal:
                # no fiscal: no hay crédito de IVA, el costo es lo que se paga (con IVA sólo si el papel lo suma aparte)
                add_tax = not inbox.prices_include_tax and inbox.amount_tax_printed
                l.price_net_untaxed = net * (1 + (l.tax_rate or 0.0) / 100.0) if add_tax else net
            else:
                l.price_net_untaxed = net / (1 + (l.tax_rate or 0.0) / 100.0) if inbox.prices_include_tax else net

    @api.depends("price_net_untaxed", "cost_current")
    def _compute_price_up(self):
        prec = self.env["decimal.precision"].precision_get("Product Price")
        tol = float(self.env["ir.config_parameter"].sudo().get_param("trx_purchase_ai_inbox.price_up_tolerance_pct", "0.5") or 0.5)
        for l in self:
            if float_is_zero(l.cost_current, precision_digits=prec):
                l.price_up, l.price_up_pct = False, 0.0
            else:
                l.price_up_pct = (l.price_net_untaxed - l.cost_current) / l.cost_current
                l.price_up = l.price_up_pct * 100.0 > tol

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.match_state, self.match_by = "matched", "manual"

    def write(self, vals):
        res = super().write(vals)
        if "product_id" in vals and not self.env.context.get("trx_inbox_internal"):
            self._snapshot_current()
        return res

    # ------------------------------------------------------------ reconocer
    def _find_product(self):
        """Orden fijo: EAN → código del proveedor → código interno → nombre (sólo sugerencia).
        Si la línea trae un EAN válido, ningún otro criterio puede asociarla a un artículo que tenga OTRO EAN
        (sería otro artículo). Los artículos archivados sólo se reconocen por EAN, y como sugerencia."""
        self.ensure_one()
        Product = self.env["product.product"]
        Seller = self.env["product.supplierinfo"]
        partner = self.inbox_id.partner_id
        ean = self.ean if (self.ean and self.ean_valid) else False

        def compatible(prod):
            return prod and not (ean and prod.barcode and prod.barcode != ean)

        if ean:
            prod = Product.search([("barcode", "=", ean)], limit=1)
            if prod:
                return prod, "matched", "ean"
            archived = Product.with_context(active_test=False).search([("barcode", "=", ean), ("active", "=", False)], limit=1)
            if archived:
                return archived, "suggested", "ean"
        if self.supplier_code and partner:
            sellers = Seller.search([("partner_id", "=", partner.id), ("product_code", "=", self.supplier_code)])
            for seller in sellers:
                prod = seller.product_id or seller.product_tmpl_id.product_variant_id
                if prod.active and compatible(prod):
                    return prod, "matched", "supplier_code"
        if self.supplier_code:
            prod = Product.search([("default_code", "=", self.supplier_code)], limit=1)
            if compatible(prod):
                return prod, "matched", "default_code"
        if self.description and len(self.description) >= 6:
            for prod in Product.search([("name", "=ilike", self.description.strip())], limit=5):
                if compatible(prod):
                    return prod, "suggested", "name"
        return Product, "new", False

    def _match_products(self):
        for line in self:
            if line.match_by in ("manual", "created") and line.product_id:
                continue
            prod, state, by = line._find_product()
            line.with_context(trx_inbox_internal=True).write({"product_id": prod.id if prod else False, "match_state": state, "match_by": by or False})
        return True

    def _snapshot_current(self):
        Seller = self.env["product.supplierinfo"]
        for line in self:
            cost = 0.0
            if line.product_id and line.inbox_id.partner_id:
                tmpl = line.product_id.product_tmpl_id
                seller = Seller.search([("partner_id", "=", line.inbox_id.partner_id.id), ("product_tmpl_id", "=", tmpl.id)], order="company_id, sequence, id", limit=1)
                if seller:
                    cost = seller.net_price * (1 - (seller.discount or 0.0) / 100.0)
                elif tmpl.replenishment_cost:
                    cost = tmpl.replenishment_cost
            line.with_context(trx_inbox_internal=True).write({"cost_current": cost})
        return True

    # ------------------------------------------------------------- acciones
    def action_confirm_suggested(self):
        for l in self.filtered(lambda l: l.match_state == "suggested" and l.product_id):
            l.with_context(trx_inbox_internal=True).write({"match_state": "matched", "match_by": "manual"})
            l._snapshot_current()
        return True

    def _default_categ(self, partner):
        """Categoría: la más usada en los artículos de ese proveedor; si no tiene, la categoría por defecto de Odoo."""
        Seller = self.env["product.supplierinfo"]
        groups = Seller._read_group([("partner_id", "=", partner.id), ("product_tmpl_id.categ_id", "!=", False)],
                                    ["product_tmpl_id.categ_id"], ["__count"], order="__count desc", limit=1) if partner else []
        if groups and groups[0][0]:
            return groups[0][0]
        Categ = self.env["product.category"]
        for ref in ("product.product_category_goods", "product.product_category_all"):
            categ = self.env.ref(ref, raise_if_not_found=False)
            if categ:
                return categ
        return Categ.search([], order="id", limit=1)

    def action_create_product(self):
        """Incorporar: crea el artículo con alfa automático del proveedor, EAN si es válido y costo = neto."""
        Tmpl = self.env["product.template"]
        Product = self.env["product.product"].with_context(active_test=False)
        created = self.env["product.template"]
        for l in self:
            if l.product_id and l.match_state == "matched":
                continue
            if l.inbox_id.state in ("done", "rejected"):
                raise UserError(_("La factura ya fue procesada."))
            partner = l.inbox_id.partner_id
            if not partner:
                raise UserError(_("Falta el proveedor de la factura."))
            barcode = l.ean if (l.ean and l.ean_valid and not Product.search_count([("barcode", "=", l.ean)])) else False
            code = partner._trx_next_alfa()
            pvp = 0.0
            if partner.trx_pvp_rule in ("list_factor", "cost_factor") and partner.trx_pvp_factor:
                pvp = l.price_net_untaxed * partner.trx_pvp_factor
                step = float(partner.trx_pvp_rounding or "0")
                pvp = round(pvp / step) * step if step > 0 else pvp
            categ = self._default_categ(partner)
            vals = {
                "name": l.description.strip(), "default_code": code, "barcode": barcode, "type": "consu", "is_storable": True,
                "categ_id": categ.id if categ else False,
                "sale_ok": True, "purchase_ok": True, "company_id": False, "list_price": pvp,
                "replenishment_cost_type": "supplier_price",
                "seller_ids": [(0, 0, {"partner_id": partner.id, "product_code": l.supplier_code or False, "product_name": l.description.strip(),
                                       "price": l.price_net_untaxed, "discount": 0.0, "min_qty": 0, "company_id": False,
                                       "date_start": l.inbox_id.invoice_date or fields.Date.context_today(l)})],
            }
            if "available_in_pos" in Tmpl._fields:
                vals["available_in_pos"] = True
            tmpl = Tmpl.with_context(trx_price_history_origin="invoice", trx_price_history_ref=l.inbox_id.name).create(vals)
            created |= tmpl
            l.with_context(trx_inbox_internal=True).write({"product_id": tmpl.product_variant_id.id, "match_state": "matched", "match_by": "created", "cost_current": l.price_net_untaxed})
        if created:
            self[0].inbox_id.message_post(body=_("Artículos incorporados: %s", ", ".join("%s %s" % (t.default_code, t.name) for t in created)))
        return True

    def action_open_product(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "product.template", "res_id": self.product_id.product_tmpl_id.id, "view_mode": "form", "target": "current"}
