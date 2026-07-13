/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { priceUnitFromInclTotal } from "@pos_promotions/app/promo_tax_utils";

patch(ControlButtons.prototype, {
    /**
     * Promo aplicada a la orden actual, resuelta desde el campo real
     * `promotion_pos_id` (Integer) contra el modelo `pos.promotion` cargado.
     *
     * IMPORTANTE: no guardar propiedades "sueltas" en el record de la orden ni
     * de la línea. El framework de modelos del POS (related_models) lanza
     * "The field 'X' does not exist in model 'Y'" al asignar algo que no es un
     * campo del modelo, y eso rompe todo el POS.
     */
    get currentPromo() {
        const id = this.currentOrder?.promotion_pos_id;
        if (!id) {
            return null;
        }
        return this.pos.models["pos.promotion"].get(id) || null;
    },

    async clickPromotion() {
        const order = this.pos.getOrder();
        const promotions = this.pos.models["pos.promotion"].getAll();
        if (!promotions.length) {
            this.dialog.add(AlertDialog, {
                title: _t("Sin promociones"),
                body: _t(
                    "No hay promociones configuradas. Cargalas en Punto de Venta → " +
                        "Configuración → Promociones."
                ),
            });
            return;
        }

        const currentId = order.promotion_pos_id || 0;
        const selectionList = [
            {
                id: 0,
                label: _t("Sin promoción"),
                isSelected: !currentId,
                item: false,
            },
            ...promotions.map((p) => ({
                id: p.id,
                label: `${p.name} — casa ${p.house_discount_pct}% / banco ${p.bank_discount_pct}%`,
                isSelected: currentId === p.id,
                item: p,
            })),
        ];

        const promo = await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Elegí una promoción"),
            list: selectionList,
        });
        // `undefined` = el cajero canceló el popup; no tocamos nada.
        if (promo === undefined) {
            return;
        }
        await this._applyPromotion(order, promo);
    },

    /**
     * Quita la promo anterior (si había) y aplica la nueva: una línea negativa
     * de descuento de la casa etiquetada con el nombre de la promo.
     *
     * Lo único que se guarda en la orden es `promotion_pos_id` (campo real, que
     * viaja al backend y dispara la NC de la devolución bancaria).
     */
    async _applyPromotion(order, promo) {
        this._removePromotionLine(order);
        order.promotion_pos_id = 0;

        if (!promo) {
            return; // "Sin promoción": queda limpia.
        }

        if (promo.house_discount_pct) {
            const product = this.pos.company.pos_promo_discount_product_id;
            if (!product) {
                this.dialog.add(AlertDialog, {
                    title: _t("Falta configuración"),
                    body: _t(
                        "No hay 'Producto para descuento de promoción' configurado en " +
                            "Punto de Venta → Configuración → Ajustes."
                    ),
                });
                return;
            }
            const houseAmount = (order.priceIncl * promo.house_discount_pct) / 100;
            if (houseAmount > 0) {
                const priceUnit = priceUnitFromInclTotal(this.pos, -houseAmount, product);
                await this.pos.addLineToCurrentOrder(
                    {
                        product_tmpl_id: product.product_tmpl_id || product,
                        product_id: product,
                        qty: 1,
                        price_unit: priceUnit,
                        note: promo.name,
                    },
                    {},
                    false
                );
            }
        }

        order.promotion_pos_id = promo.id;
    },

    /**
     * La línea de descuento se identifica por el producto de descuento de la
     * compañía (no usamos flags sueltos en el record: el POS los rechaza).
     */
    _removePromotionLine(order) {
        const product = this.pos.company.pos_promo_discount_product_id;
        if (!product) {
            return;
        }
        for (const line of [...(order.lines || [])]) {
            if (line.product_id && line.product_id.id === product.id) {
                order.removeOrderline(line);
            }
        }
    },
});
