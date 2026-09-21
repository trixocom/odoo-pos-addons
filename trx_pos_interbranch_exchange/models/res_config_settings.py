# Part of trx_pos_interbranch_exchange. Author: Trixocom. License: LGPL-3.
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # Sucursal (parent_id): la configuración se hereda de la raíz → solo lectura acá.
    trx_ibx_is_branch = fields.Boolean(compute="_compute_trx_ibx_is_branch")
    trx_ibx_root_company_name = fields.Char(compute="_compute_trx_ibx_is_branch")
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

    @api.depends("company_id")
    def _compute_trx_ibx_is_branch(self):
        for rec in self:
            rec.trx_ibx_is_branch = bool(rec.company_id.parent_id)
            rec.trx_ibx_root_company_name = rec.company_id.root_id.name

    def action_trx_ibx_setup(self):
        return self.company_id.action_trx_ibx_setup()
