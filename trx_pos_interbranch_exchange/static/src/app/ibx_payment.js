/** @odoo-module */
import { _t } from "@web/core/l10n/translation";
import { PaymentInterface } from "@point_of_sale/app/utils/payment/payment_interface";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { IbxExchangePopup } from "@trx_pos_interbranch_exchange/app/ibx_popup/ibx_popup";

/**
 * Payment interface "interbranch_exchange" (Trixocom).
 *
 * Al elegir el medio de pago se abre un popup para escanear/tipear el código
 * del ticket de cambio. El popup busca la venta original (puede ser de otra
 * compañía), deja elegir productos/cantidades y PREPARA el cambio en el
 * servidor (estado draft). El importe queda como pago de la venta nueva.
 * La NC en la compañía que vendió, la compensación y el ingreso de stock se
 * ejecutan en el servidor al confirmar la venta, en la misma transacción.
 */
export class InterbranchExchange extends PaymentInterface {
    async sendPaymentRequest(uuid) {
        await super.sendPaymentRequest(...arguments);
        const order = this.pos.getOrder();
        const line = order.getSelectedPaymentline() || order.payment_ids.find((p) => p.uuid === uuid);
        if (!line) {
            return false;
        }
        // Al agregarse, la línea nace con el importe adeudado: es el tope del cambio
        // salvo que la compañía permita devolver la diferencia en efectivo.
        const maxAmount = line.amount;
        line.setPaymentStatus("waitingCapture");
        try {
            const accepted = await ask(
                this.env.services.dialog,
                {
                    title: _t("Cambio inter-sucursal"),
                    line: line,
                    order: order,
                    pos: this.pos,
                    maxAmount: maxAmount,
                    allowCashDifference: !!this.pos.company.trx_ibx_allow_cash_difference,
                },
                {},
                IbxExchangePopup
            );
            if (!accepted) {
                line.setPaymentStatus("retry");
                return false;
            }
            return true;
        } catch (error) {
            console.error(error);
            this._showMsg(_t("Error procesando el cambio inter-sucursal"), _t("Error"));
            line.setPaymentStatus("retry");
            return false;
        }
    }

    async sendPaymentCancel(order, uuid) {
        await super.sendPaymentCancel(order, uuid);
        const line = order.payment_ids.find((p) => p.uuid === uuid);
        if (line && line.trx_ibx_exchange_id) {
            try {
                await this.env.services.orm.call("trx.ibx.exchange", "ibx_cancel_draft", [
                    line.trx_ibx_exchange_id,
                ]);
            } catch (error) {
                console.error(error);
            }
            line.trx_ibx_exchange_id = 0;
        }
        return true;
    }

    _showMsg(msg, title) {
        this.env.services.dialog.add(AlertDialog, { title: title, body: msg });
    }
}
