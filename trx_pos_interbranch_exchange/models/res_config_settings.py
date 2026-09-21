# Part of trx_pos_interbranch_exchange. Author: Trixocom. License: LGPL-3.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    trx_ibx_days_limit = fields.Integer(
        related="company_id.trx_ibx_days_limit", readonly=False
    )
    trx_ibx_allow_cash_difference = fields.Boolean(
        related="company_id.trx_ibx_allow_cash_difference", readonly=False
    )
    trx_ibx_nf_journal_id = fields.Many2one(
        related="company_id.trx_ibx_nf_journal_id", readonly=False
    )
    trx_ibx_account_id = fields.Many2one(related="company_id.trx_ibx_account_id")
    trx_ibx_payment_method_id = fields.Many2one(
        related="company_id.trx_ibx_payment_method_id"
    )

    def action_trx_ibx_setup(self):
        return self.company_id.action_trx_ibx_setup()
