/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";

/**
 * Getters para el ticket: resuelven la promo desde el campo real
 * `promotion_pos_id` de la orden contra el modelo `pos.promotion` cargado.
 *
 * No guardamos el nombre/% de la promo como propiedades sueltas en el record:
 * el framework de modelos del POS lanza excepción al asignar algo que no es un
 * campo del modelo. Al resolverlo desde el id, además funciona en la reimpresión
 * de un ticket ya guardado.
 */
patch(OrderReceipt.prototype, {
    setup() {
        super.setup();
        this.posService = usePos();
    },

    get promo() {
        const id = this.order?.promotion_pos_id;
        if (!id) {
            return null;
        }
        return this.posService.models["pos.promotion"].get(id) || null;
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
