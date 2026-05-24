from odoo import api, fields, models


class AccountCard(models.Model):
    _name = "account.card"
    _inherit = ["account.card", "pos.load.mixin"]

    available_in_pos = fields.Boolean(
        string="Available in POS",
        help="Tildá esta tarjeta para que se ofrezca al cobrar en el Punto de Venta.",
        default=False,
    )

    @api.model
    def _load_pos_data_domain(self, data, config):
        # Filtramos por company (fix de bug multi-company del módulo 18)
        # y sólo cargamos tarjetas explícitamente marcadas como disponibles
        # en POS (fix del flag available_in_pos que en 18 no filtraba nada).
        return self.env["account.card"]._check_company_domain(config.company_id) + [
            ("available_in_pos", "=", True),
            ("active", "=", True),
        ]

    @api.model
    def _load_pos_data_fields(self, config):
        return ["id", "name", "installment_ids", "available_in_pos"]
