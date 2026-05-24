/** @odoo-module */
import { _t } from "@web/core/l10n/translation";
import { PaymentInterface } from "@point_of_sale/app/utils/payment/payment_interface";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { FinancialSurchargePopup } from "@pos_financial_surcharge/app/financial_surcharge_popup/financial_surcharge_popup";

/**
 * Payment interface "financial_surcharge".
 *
 * Al apretar el método de pago se abre un popup con los planes de cuotas
 * disponibles para las tarjetas configuradas en `available_card_ids`. El
 * popup es el que aplica el recargo/descuento sobre la orden; esta interface
 * solo orquesta el lifecycle del payment line.
 */
export class FinancialSurcharge extends PaymentInterface {
    _getCards() {
        const installments = this.pos.models["account.card.installment"].getAll();
        const availableCardIds = (this.payment_method_id.available_card_ids || []).map(
            (c) => c.id
        );
        const cards = this.pos.models["account.card"]
            .getAll()
            .filter((card) => availableCardIds.includes(card.id));

        // Index O(n+m) en vez de O(n*m) del original
        const byCard = new Map();
        for (const inst of installments) {
            const cardId = inst.card_id?.id;
            if (!cardId) continue;
            if (!byCard.has(cardId)) byCard.set(cardId, []);
            byCard.get(cardId).push({
                id: inst.id,
                name: inst.name,
                divisor: inst.divisor,
                installment: inst.installment,
                surcharge_coefficient: inst.surcharge_coefficient,
                bank_discount: inst.bank_discount,
            });
        }
        return cards.map((card) => ({
            id: card.id,
            name: card.name,
            installments: byCard.get(card.id) || [],
        }));
    }

    async sendPaymentRequest(uuid) {
        await super.sendPaymentRequest(...arguments);
        const order = this.pos.getOrder();
        const line = order.getSelectedPaymentline();
        if (!line) {
            return false;
        }

        const cards = this._getCards();
        if (!cards.length || cards.every((c) => !c.installments.length)) {
            this._showMsg(
                _t(
                    "No hay planes de cuotas configurados para las tarjetas de este método de pago."
                ),
                _t("Error de configuración")
            );
            line.setPaymentStatus("retry");
            return false;
        }

        // Guard del producto de recargo: si la company no lo tiene seteado y
        // existen planes con coeficiente != 1, abortamos limpio (fix bug #3).
        const product = this.pos.company.product_surcharge_id;
        const hasNonNeutralPlan = cards.some((c) =>
            c.installments.some((i) => i.surcharge_coefficient !== 1.0)
        );
        if (hasNonNeutralPlan && !product) {
            this._showMsg(
                _t(
                    "Falta configurar el 'Producto para recargo financiero' en " +
                        "Punto de Venta → Ajustes."
                ),
                _t("Error de configuración")
            );
            line.setPaymentStatus("retry");
            return false;
        }

        line.setPaymentStatus("waitingCapture");
        try {
            const accepted = await ask(
                this.env.services.dialog,
                {
                    title: _t("Seleccionar plan de cuotas"),
                    line: line,
                    cards: cards,
                    order: order,
                    pos: this.pos,
                },
                {},
                FinancialSurchargePopup
            );

            if (!accepted) {
                // Restauramos el estado al cancelar (fix bug #6).
                line.setPaymentStatus("retry");
                return false;
            }
            return true;
        } catch (error) {
            console.error(error);
            this._showMsg(_t("Error procesando el plan financiero"), _t("Error"));
            line.setPaymentStatus("retry");
            return false;
        }
    }

    async sendPaymentCancel(order, uuid) {
        await super.sendPaymentCancel(order, uuid);
        return true;
    }

    _showMsg(msg, title) {
        this.env.services.dialog.add(AlertDialog, {
            title: title,
            body: msg,
        });
    }
}
