# Part of trx_pos_interbranch_exchange. Author: Trixocom. License: LGPL-3.
from odoo import models


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    def _get_payment_terminal_selection(self):
        return super()._get_payment_terminal_selection() + [
            ("interbranch_exchange", "Cambio inter-sucursal")
        ]
