# Part of trx_multicompany_reports. Author: Trixocom. License: LGPL-3.
from odoo import fields, models
from odoo.tools import SQL


class AccountInvoiceReport(models.Model):
    _inherit = "account.invoice.report"

    trx_root_company_id = fields.Many2one("res.company", string="Razón social (CUIT)", readonly=True)

    def _select(self) -> SQL:
        return SQL(
            "%s, NULLIF(split_part(trx_co.parent_path, '/', 1), '')::int AS trx_root_company_id",
            super()._select(),
        )

    def _from(self) -> SQL:
        return SQL(
            "%s LEFT JOIN res_company trx_co ON trx_co.id = line.company_id",
            super()._from(),
        )
