from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_trx_cash_reason_required = fields.Boolean(
        related="pos_config_id.trx_cash_reason_required",
        readonly=False,
    )
