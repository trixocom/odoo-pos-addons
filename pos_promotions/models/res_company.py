from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    pos_promo_discount_product_id = fields.Many2one(
        "product.product",
        string="Producto para descuento de promoción",
        help="Producto usado como ítem (línea negativa) cuando se aplica el "
        "descuento de la casa de una promoción. Debe estar disponible en POS y "
        "tener configurado el IVA correspondiente (normalmente 21%) para que el "
        "descuento reduzca la base imponible correctamente.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ["pos_promo_discount_product_id"]
