from odoo import api, models


class AccountCardInstallment(models.Model):
    _name = "account.card.installment"
    _inherit = ["account.card.installment", "pos.load.mixin"]

    @api.model
    def _load_pos_data_domain(self, data, config):
        # Fix multi-company: cargamos sólo los planes cuya tarjeta padre
        # pertenece a la misma company del POS (en 18 se devolvía [] y se
        # cargaban planes de todas las companies).
        return [
            ("active", "=", True),
            ("card_id.company_id", "in", config.company_id.ids + [False]),
            ("card_id.available_in_pos", "=", True),
        ]

    @api.model
    def _load_pos_data_fields(self, config):
        return [
            "id",
            "card_id",
            "name",
            "divisor",
            "installment",
            "surcharge_coefficient",
            "bank_discount",
        ]
