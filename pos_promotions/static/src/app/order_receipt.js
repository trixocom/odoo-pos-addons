/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

/**
 * Getters para el ticket: resuelven la promo desde el campo real
 * `promotion_pos_id` de la orden contra el modelo `pos.promotion` cargado.
 *
 * Notas de implementación (dos trampas del POS de Odoo 19):
 *  1. NO guardar propiedades sueltas en los records (order/line): el framework
 *     de modelos lanza "The field 'X' does not exist in model 'Y'".
 *  2. NO patchear `setup()` de OrderReceipt: el componente no define `setup`
 *     propio, y el `super.setup()` del patch rompe el bundle entero (POS en
 *     blanco). Por eso resolvemos el modelo con `record.models`, que ya expone
 *     el registry (related_models: `get models()`), sin hooks.
 */
patch(OrderReceipt.prototype, {
    get promo() {
        const order = this.order;
        const id = order && order.promotion_pos_id;
        if (!id) {
            return null;
        }
        const model = order.models && order.models["pos.promotion"];
        return (model && model.get(id)) || null;
    },

    /** Importe que devuelve el banco, según la base configurada en la promo. */
    get promoBankAmount() {
        const promo = this.promo;
        if (!promo || !promo.bank_discount_pct) {
            return 0;
        }
        const base =
            promo.bank_base === "untaxed" ? this.order.priceExcl : this.order.priceIncl;
        return (base * promo.bank_discount_pct) / 100;
    },
});
