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
     * Abre el selector de promociones y aplica la elegida sobre la orden.
     */
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

        const current = order.promotion_id;
        const selectionList = [
            {
                id: 0,
                label: _t("Sin promoción"),
                isSelected: !current,
                item: false,
            },
            ...promotions.map((p) => ({
                id: p.id,
                label: _t("%(name)s — casa %(house)s%% / banco %(bank)s%%", {
                    name: p.name,
                    house: p.house_discount_pct,
                    bank: p.bank_discount_pct,
                }),
                isSelected: current && current.id === p.id,
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
     * de descuento de la casa etiquetada con el nombre de la promo, y guarda los
     * datos del reintegro del banco para el ticket y la NC fiscal.
     */
    async _applyPromotion(order, promo) {
        // 1) Sacar la línea de descuento de una promo previa.
        this._removePromotionLine(order);
        order.promotion_id = false;
        order.promo_bank_pct = 0;
        order.promo_bank_amount = 0;

        if (!promo) {
            return; // "Sin promoción": ya quedó limpia.
        }

        // 2) Descuento de la casa como línea negativa única.
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
                const line = await this.pos.addLineToCurrentOrder(
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
                if (line) {
                    line.promo_discount_line = true;
                }
            }
        }

        // 3) Datos del reintegro del banco (no descuenta: solo informa + NC).
        order.promotion_id = promo;
        order.promo_bank_pct = promo.bank_discount_pct || 0;
        if (promo.bank_discount_pct) {
            const bankBase =
                promo.bank_base === "untaxed" ? order.priceExcl : order.priceIncl;
            order.promo_bank_amount = (bankBase * promo.bank_discount_pct) / 100;
        }
    },

    _removePromotionLine(order) {
        const product = this.pos.company.pos_promo_discount_product_id;
        const lines = [...(order.lines || [])];
        for (const line of lines) {
            const isFlagged = line.promo_discount_line;
            const isDiscountProduct =
                product && line.product_id && line.product_id.id === product.id;
            if (isFlagged || isDiscountProduct) {
                order.removeOrderline(line);
            }
        }
    },
});
