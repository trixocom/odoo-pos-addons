from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    trx_cash_reason_required = fields.Boolean(
        string="Require Cash In/Out Reason",
        default=True,
        help="When reasons are available for the kind of cash move, the cashier must "
        "select one. The free text becomes an optional note.",
    )
