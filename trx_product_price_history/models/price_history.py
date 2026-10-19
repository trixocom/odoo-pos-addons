# Part of trx_product_price_history. Author: Trixocom. License: LGPL-3.
from odoo import api, fields, models
from odoo.tools import float_compare, float_is_zero

PRICE_TYPES = [
    ("list_price", "PVP"),
    ("standard_price", "Costo contable"),
    ("supplier_price", "Precio de proveedor"),
]

ORIGINS = [
    ("product", "Ficha del artículo"),
    ("supplierinfo", "Lista de proveedor (ficha)"),
    ("revision", "Revisión de lista de proveedor"),
    ("planned", "Precio planificado / sincronización (cron)"),
    ("purchase", "Orden de compra"),
    ("invoice", "Factura de proveedor"),
    ("import", "Importación"),
    ("other", "Otro"),
]

# Claves de contexto que usan los módulos que escriben precios para identificar el origen.
CTX_SKIP = "trx_price_history_skip"
CTX_ORIGIN = "trx_price_history_origin"
CTX_REF = "trx_price_history_ref"
CTX_DATE = "trx_price_history_date"
CTX_REASON = "trx_price_history_reason"


class TrxProductPriceHistory(models.Model):
    _name = "trx.product.price.history"
    _description = "Historial de precios de artículos"
    _order = "date desc, id desc"

    product_tmpl_id = fields.Many2one(
        "product.template", string="Artículo", required=True, index=True, ondelete="cascade"
    )
    product_id = fields.Many2one("product.product", string="Variante", index=True, ondelete="cascade")
    default_code = fields.Char(related="product_tmpl_id.default_code", string="Código alfa", store=True)
    categ_id = fields.Many2one(related="product_tmpl_id.categ_id", string="Categoría", store=True)
    price_type = fields.Selection(PRICE_TYPES, string="Tipo", required=True, index=True)
    company_id = fields.Many2one("res.company", string="Razón social", index=True)
    partner_id = fields.Many2one("res.partner", string="Proveedor", index=True)
    supplierinfo_id = fields.Many2one("product.supplierinfo", string="Línea de proveedor", ondelete="set null")
    currency_id = fields.Many2one(
        "res.currency", string="Moneda", default=lambda self: self.env.company.currency_id.id
    )
    old_value = fields.Monetary(string="Anterior", currency_field="currency_id")
    new_value = fields.Monetary(string="Nuevo", currency_field="currency_id")
    variation = fields.Monetary(string="Diferencia", currency_field="currency_id", compute="_compute_variation", store=True)
    variation_pct = fields.Float(string="Variación", compute="_compute_variation", store=True, digits=(16, 4),
                                 help="Variación como fracción: 0,10 = +10 %.")
    date = fields.Datetime(string="Vigencia", required=True, default=fields.Datetime.now, index=True)
    user_id = fields.Many2one("res.users", string="Usuario", default=lambda self: self.env.uid)
    origin = fields.Selection(ORIGINS, string="Origen", required=True, default="product", index=True)
    origin_ref = fields.Char(string="Referencia")
    reason = fields.Char(string="Motivo")

    @api.depends("old_value", "new_value")
    def _compute_variation(self):
        for rec in self:
            rec.variation = rec.new_value - rec.old_value
            rec.variation_pct = (rec.new_value - rec.old_value) / rec.old_value if rec.old_value else 0.0

    @api.model
    def _log(self, product_tmpl, price_type, old_value, new_value, product=None, company=None,
             partner=None, supplierinfo=None, origin=None, origin_ref=None, reason=None, date=None):
        """Crea una fila de historial si el valor cambió. Respeta las claves de contexto."""
        ctx = self.env.context
        if ctx.get(CTX_SKIP):
            return self.browse()
        prec = self.env["decimal.precision"].precision_get("Product Price")
        if float_compare(old_value or 0.0, new_value or 0.0, precision_digits=prec) == 0:
            return self.browse()
        vals = {
            "product_tmpl_id": product_tmpl.id,
            "product_id": product.id if product else (
                product_tmpl.product_variant_id.id if product_tmpl.product_variant_count == 1 else False
            ),
            "price_type": price_type,
            "company_id": company.id if company else False,
            "partner_id": partner.id if partner else False,
            "supplierinfo_id": supplierinfo.id if supplierinfo else False,
            "currency_id": (company or self.env.company).currency_id.id,
            "old_value": old_value or 0.0,
            "new_value": new_value or 0.0,
            "origin": origin or ctx.get(CTX_ORIGIN) or "product",
            "origin_ref": origin_ref or ctx.get(CTX_REF) or False,
            "reason": reason or ctx.get(CTX_REASON) or False,
            "date": date or ctx.get(CTX_DATE) or fields.Datetime.now(),
            "user_id": self.env.uid,
        }
        return self.sudo().create(vals)

    @api.model
    def _previous_value(self, product_tmpl, price_type, partner=None, company=None):
        """Valor anterior registrado más reciente para el artículo y tipo (0 si no hay)."""
        domain = [("product_tmpl_id", "=", product_tmpl.id), ("price_type", "=", price_type)]
        if partner:
            domain.append(("partner_id", "=", partner.id))
        if company:
            domain.append(("company_id", "=", company.id))
        rec = self.sudo().search(domain, limit=1)
        return rec.old_value if rec else 0.0

    def _is_zero(self, value):
        prec = self.env["decimal.precision"].precision_get("Product Price")
        return float_is_zero(value, precision_digits=prec)
