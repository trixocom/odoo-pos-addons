from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_promo_discount_product_id = fields.Many2one(
        related="company_id.pos_promo_discount_product_id",
        readonly=False,
    )
