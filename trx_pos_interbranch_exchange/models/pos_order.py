# Part of trx_pos_interbranch_exchange. Author: Trixocom. License: LGPL-3.
import logging

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _process_order(self, order, existing_order):
        """Al sincronizar la venta nueva (B) se ejecutan los cambios inter-sucursal
        preparados desde el POS, en la MISMA transacción: si algo falla (p.ej. AFIP
        rechaza la NC en A) la venta no se graba y el POS muestra el error."""
        order_id = super()._process_order(order, existing_order)
        pos_order = self.browse(order_id)
        if pos_order.state not in ("paid", "done", "invoiced"):
            return order_id
        payments = pos_order.payment_ids.filtered("trx_ibx_exchange_id")
        if not payments:
            return order_id
        Exchange = self.env["trx.ibx.exchange"].sudo()
        for payment in payments:
            exchange = Exchange.browse(payment.trx_ibx_exchange_id).exists()
            if not exchange:
                raise UserError(_("El cambio inter-sucursal del pago %s ya no existe.", payment.amount))
            if exchange.state == "done":
                continue
            if exchange.state == "cancel":
                raise UserError(_("El cambio inter-sucursal %s fue cancelado; quitá el pago y volvé a escanear.", exchange.name))
            exchange._ibx_execute(pos_order, payment)
        return order_id

    def action_print_ticket_cambio(self):
        return self.env.ref("trx_pos_interbranch_exchange.action_report_ticket_cambio").report_action(self)

    def _trx_ibx_ticket_lines(self):
        """Líneas para el ticket de cambio: sin precios, solo lo cambiable."""
        self.ensure_one()
        return self.lines.filtered(lambda l: l.qty > 0 and l.product_id.is_storable)
