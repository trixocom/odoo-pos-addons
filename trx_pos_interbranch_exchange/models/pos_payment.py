# Part of trx_pos_interbranch_exchange. Author: Trixocom. License: LGPL-3.
from odoo import fields, models


class PosPayment(models.Model):
    _inherit = "pos.payment"

    # Escalar a propósito: el POS solo puede escribir campos REALES del modelo
    # (ver nota en pos_financial_surcharge). Guarda el id del trx.ibx.exchange
    # preparado desde el popup; el servidor lo ejecuta al sincronizar la orden.
    trx_ibx_exchange_id = fields.Integer(
        string="Cambio inter-sucursal (id)", copy=False, index=True
    )
