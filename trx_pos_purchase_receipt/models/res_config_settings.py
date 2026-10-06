from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_trx_receipt_enabled = fields.Boolean(related="pos_config_id.trx_receipt_enabled", readonly=False)
    pos_trx_receipt_blind = fields.Boolean(related="pos_config_id.trx_receipt_blind", readonly=False)
    pos_trx_receipt_label_format = fields.Selection(
        related="pos_config_id.trx_receipt_label_format", readonly=False
    )
