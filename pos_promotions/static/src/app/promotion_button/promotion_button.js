/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

patch(ControlButtons.prototype, {
    /**
     * Promo aplicada a la orden actual, resuelta desde el campo real
     * `promotion_pos_id` contra el modelo `pos.promotion` cargado.
     *
     * IMPORTANTE: no guardar propiedades "sueltas" en el record de la orden ni
     * de la línea. related_models lanza "The field 'X' does not exist in model
     * 'Y'" al asignar algo que no es un campo, y eso rompe el POS entero.
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
            { id: 0, label: _t("Sin promoción"), isSelected: !currentId, item: false },
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
        if (promo === undefined) {
            return; // el cajero canceló
        }
        await this._applyPromotion(order, promo);
    },

    /**
     * Quita la promo anterior y aplica la nueva: una línea negativa de descuento
     * de la casa etiquetada con el nombre de la promo. Lo único que se guarda en
     * la orden es `promotion_pos_id` (campo real, viaja al backend y dispara la
     * NC de la devolución bancaria).
     *
     * Todo va dentro de un try/catch: si algo falla, mostramos el error en un
     * diálogo en vez de dejar el POS en blanco.
     */
    async _applyPromotion(order, promo) {
        try {
            this._removePromotionLine(order);
            order.promotion_pos_id = 0;

            if (!promo) {
                return; // "Sin promoción"
            }

            if (promo.house_discount_pct) {
                const product = this.pos.company.pos_promo_discount_product_id;
                if (!product) {
                    this.dialog.add(AlertDialog, {
                        title: _t("Falta configuración"),
                        body: _t(
                            "No hay 'Producto para descuento de promoción' configurado " +
                                "en Punto de Venta → Configuración → Ajustes."
                        ),
                    });
                    return;
                }
                const houseAmount = (order.priceIncl * promo.house_discount_pct) / 100;
                if (houseAmount > 0) {
                    // price_unit (neto) tal que el total CON impuestos de la línea
                    // sea -houseAmount. Sumamos las alícuotas de los impuestos del
                    // producto que NO están incluidos en el precio.
                    const taxes = (product.taxes_id || []).filter(
                        (t) => !t.price_include && t.amount_type === "percent"
                    );
                    const rate =
                        taxes.reduce((sum, t) => sum + (t.amount || 0), 0) / 100;
                    const priceUnit = -houseAmount / (1 + rate);

                    // OJO: en Odoo 19 `note` de la orderline es un ARRAY JSON
                    // (se hace JSON.parse al renderizar: orderline.js →
                    // `internalNote: JSON.parse(line.note || "[]")`). Pasarle
                    // texto plano rompe el render y deja el POS en blanco.
                    const note = JSON.stringify([
                        { text: promo.name, colorIndex: 0 },
                    ]);

                    await this.pos.addLineToCurrentOrder(
                        {
                            product_tmpl_id: product.product_tmpl_id,
                            product_id: product,
                            qty: 1,
                            price_unit: priceUnit,
                            note: note,
                        },
                        {},
                        false
                    );
                }
            }

            order.promotion_pos_id = promo.id;
        } catch (error) {
            this.dialog.add(AlertDialog, {
                title: _t("Error aplicando la promoción"),
                body: String((error && (error.message || error.name)) || error),
            });
        }
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
