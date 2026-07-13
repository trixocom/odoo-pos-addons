/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

/**
 * Resuelve el plan de cuotas de una línea de pago desde el campo REAL
 * `card_installment_pos_id` contra el modelo `account.card.installment` cargado.
 *
 * Dos trampas del POS de Odoo 19 que motivan este diseño:
 *  1. No se pueden guardar propiedades sueltas en los records (antes se seteaba
 *     `line.cardPlanName` / `cardBankDiscount`): related_models lanza
 *     "The field 'X' does not exist in model 'Y'" y deja el POS en blanco.
 *  2. No patchear `setup()` de OrderReceipt: el componente no define uno propio y
 *     el `super.setup()` del patch rompe el bundle entero. Por eso usamos
 *     `record.models`, que related_models ya expone (`get models()`).
 */
patch(OrderReceipt.prototype, {
    getCardPlan(line) {
        const id = line && line.card_installment_pos_id;
        if (!id) {
            return null;
        }
        const model = line.models && line.models["account.card.installment"];
        return (model && model.get(id)) || null;
    },
});
