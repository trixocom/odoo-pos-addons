# Part of trx_multicompany_reports. Author: Trixocom. License: LGPL-3.
from odoo import api, fields, models


class TrxRootCompanyMixin(models.AbstractModel):
    """Agrega 'Razón social (CUIT)' = compañía raíz de company_id, almacenado.

    `res.company.root_id` es un campo calculado NO almacenado, así que no sirve
    para agrupar en pivots ni para filtrar por SQL. La jerarquía de compañías
    no puede cambiar una vez creada (base lo prohíbe en write), por lo que
    almacenarlo es seguro.
    """

    _name = "trx.root.company.mixin"
    _description = "Razón social (compañía raíz) - mixin"

    trx_root_company_id = fields.Many2one(
        "res.company",
        string="Razón social (CUIT)",
        compute="_compute_trx_root_company_id",
        store=True,
        index=True,
        readonly=True,
        compute_sudo=True,
        help="Compañía raíz de la compañía del registro: la razón social / CUIT. "
        "Si la compañía es una sucursal (tiene compañía padre), es su raíz; "
        "si no, es la misma compañía.",
    )

    @api.depends("company_id")
    def _compute_trx_root_company_id(self):
        for rec in self:
            company = rec.company_id
            rec.trx_root_company_id = company.root_id if company else False
