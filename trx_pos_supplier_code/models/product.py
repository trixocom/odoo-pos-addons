from odoo import api, fields, models
from odoo.fields import Domain

POSITIVE_OPS = ("ilike", "=ilike", "like", "=like", "=")


class ProductTemplate(models.Model):
    _inherit = "product.template"

    trx_supplier_codes = fields.Char(
        string="Códigos de proveedor",
        compute="_compute_trx_supplier_codes",
        store=True,
        index="trigram",
        help="Códigos de artículo de todos los proveedores del producto (para buscar en el POS y en los listados).",
    )

    @api.depends("seller_ids.product_code", "seller_ids.product_id")
    def _compute_trx_supplier_codes(self):
        for tmpl in self:
            codes = []
            for code in tmpl.seller_ids.mapped("product_code"):
                code = (code or "").strip()
                if code and code not in codes and code != tmpl.default_code:
                    codes.append(code)
            tmpl.trx_supplier_codes = " ".join(codes) or False

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ["trx_supplier_codes"]

    @api.model
    def _search_display_name(self, operator, value):
        domain = super()._search_display_name(operator, value)
        if value and isinstance(value, str) and operator in POSITIVE_OPS:
            domain = Domain.OR([Domain("trx_supplier_codes", "ilike", value), Domain(domain)])
        return domain


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _search_display_name(self, operator, value):
        domain = super()._search_display_name(operator, value)
        if value and isinstance(value, str) and operator in POSITIVE_OPS:
            domain = Domain.OR([Domain("product_tmpl_id.trx_supplier_codes", "ilike", value), Domain(domain)])
        return domain
