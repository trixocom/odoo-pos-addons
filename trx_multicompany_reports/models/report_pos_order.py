# Part of trx_multicompany_reports. Author: Trixocom. License: LGPL-3.
from odoo import fields, models


class ReportPosOrder(models.Model):
    _inherit = "report.pos.order"

    trx_root_company_id = fields.Many2one("res.company", string="Razón social (CUIT)", readonly=True)

    def _select(self):
        # `co` = res_company de la orden (ya unida en _from). La raíz es el
        # primer id de parent_path ('5/7/' -> 5).
        return super()._select() + """,
                NULLIF(split_part(co.parent_path, '/', 1), '')::int AS trx_root_company_id
        """
