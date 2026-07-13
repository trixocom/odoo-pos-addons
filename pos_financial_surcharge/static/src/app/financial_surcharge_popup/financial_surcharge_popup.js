/** @odoo-module */
import { useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import {
    AlertDialog,
    ConfirmationDialog,
} from "@web/core/confirmation_dialog/confirmation_dialog";
import { accountTaxHelpers } from "@account/helpers/account_tax";

/**
 * Popup que el cajero usa para elegir un plan financiero.
 *
 * El popup NO toca el `payment_status` (lo hace la PaymentInterface, fix bug
 * #7). Su única responsabilidad es: insertar la orderline con el delta del
 * recargo/descuento y actualizar el amount del payment line.
 */
export class FinancialSurchargePopup extends ConfirmationDialog {
    static template = "pos_financial_surcharge.FinancialSurchargeConfirmationDialog";
    static props = {
        ...ConfirmationDialog.props,
        line: Object,
        order: Object,
        cards: Object,
        pos: Object,
    };
    static defaultProps = {
        ...ConfirmationDialog.defaultProps,
        confirmLabel: _t("Confirmar pago"),
        cancelLabel: _t("Cancelar pago"),
        title: _t("Plan financiero"),
    };

    setup() {
        super.setup();
        this.state = useState({
            rawAmount: this.props.line.amount,
            selectedInstallment: false,
        });
    }

    get rawAmount() {
        return this.state.rawAmount;
    }

    get amountDisplay() {
        return this.env.utils.formatCurrency(this.state.rawAmount);
    }

    formatCurrency(amount) {
        return this.env.utils.formatCurrency(amount);
    }

    /**
     * Calcula el priceIncluded de una baseLine con un price_unit y el set de
     * impuestos no incluidos en precio del producto de recargo.
     */
    _computeInclWithPriceUnit(priceUnit, taxes, company) {
        const baseLine = accountTaxHelpers.prepare_base_line_for_taxes_computation(
            {},
            {
                tax_ids: taxes,
                quantity: 1,
                price_unit: priceUnit,
                currency_id: this.props.pos.currency,
            }
        );
        accountTaxHelpers.add_tax_details_in_base_line(baseLine, company);
        accountTaxHelpers.round_base_lines_tax_details([baseLine], company);
        return baseLine.tax_details.total_included_currency;
    }

    /**
     * Calcula el price_unit (sin impuesto) tal que el total INCLUIDO de la
     * orderline sea exactamente `targetIncl`. En Odoo 18 esto lo hacía
     * `compute_price_force_price_include`, que en 19 ya no existe: usamos
     * el helper de account_tax y, si el resultado no cae en la grilla del
     * currency rounding, hacemos una búsqueda fina en ±N pasos de rounding
     * para minimizar el error de centavos (fix bug #19).
     *
     * @param {number} targetIncl monto con impuestos incluidos (puede ser <0)
     * @param {object} product product.product del recargo
     * @returns {number} price_unit
     */
    _priceUnitFromInclTotal(targetIncl, product) {
        const company = this.props.pos.company;
        const taxes = (product.taxes_id || []).filter(
            (t) => !t.company_id || t.company_id.id === company.id
        );
        if (!taxes.length) {
            return targetIncl;
        }
        // Sólo importan los impuestos NO incluidos en precio (los que suman).
        const taxesAddingUp = taxes.filter((t) => !t.price_include);
        if (!taxesAddingUp.length) {
            return targetIncl;
        }
        // 1) Estimación analítica: priceUnit = targetIncl² / totalIncl(con pu=targetIncl)
        const inclWithTarget = this._computeInclWithPriceUnit(
            targetIncl,
            taxes,
            company
        );
        if (!inclWithTarget) {
            return targetIncl;
        }
        let bestPu = (targetIncl * targetIncl) / inclWithTarget;

        // 2) Refinamiento fino: probamos ±2 pasos de currency.rounding sobre
        //    el redondeo natural del price_unit, y nos quedamos con el que
        //    produzca el priceIncluded más cercano a targetIncl. Esto evita
        //    perder centavos cuando el cociente no cae en la grilla.
        const rounding = this.props.pos.currency?.rounding || 0.01;
        const roundedPu = Math.round(bestPu / rounding) * rounding;
        let bestDiff = Number.POSITIVE_INFINITY;
        let bestRefined = roundedPu;
        for (let step = -2; step <= 2; step += 1) {
            const testPu = roundedPu + step * rounding;
            const incl = this._computeInclWithPriceUnit(testPu, taxes, company);
            if (incl === undefined || incl === null) continue;
            const diff = Math.abs(incl - targetIncl);
            if (diff < bestDiff) {
                bestDiff = diff;
                bestRefined = testPu;
            }
        }
        return bestRefined;
    }

    async _confirm() {
        if (!this.state.selectedInstallment) {
            this._showMsg(_t("Tenés que elegir un plan de cuotas"), _t("Atención"));
            return false;
        }
        const installments =
            this.props.pos.models["account.card.installment"].getAllBy("id");
        const inst = installments[this.state.selectedInstallment];
        const coef = inst.surcharge_coefficient || 1.0;
        const diffAmount = this.state.rawAmount * coef - this.state.rawAmount;

        // Coeficiente 1.0 (sin recargo): no agregamos línea, sólo cerramos.
        if (!diffAmount) {
            // OJO: en Odoo 19 no se pueden asignar propiedades "sueltas" a un
            // record del POS: related_models lanza "The field 'X' does not exist
            // in model 'Y'" y deja el POS en blanco. Guardamos el id del plan en
            // un campo REAL de pos.payment (card_installment_pos_id) y el resto
            // (nombre, reintegro, cuotas) se resuelve desde el modelo cargado.
            this.props.line.card_installment_pos_id = inst.id;
            return this.execButton(this.props.confirm);
        }

        const product = this.props.pos.company.product_surcharge_id;
        if (!product) {
            // Doble guard: ya lo chequeó la PaymentInterface, pero por las dudas.
            this._showMsg(
                _t(
                    "No hay producto de recargo financiero configurado para esta empresa."
                ),
                _t("Error de configuración")
            );
            return false;
        }

        const priceUnit = this._priceUnitFromInclTotal(diffAmount, product);
        // OJO: en Odoo 19 el `note` de la orderline es un ARRAY JSON — al
        // renderizar se hace JSON.parse(line.note) (orderline.js →
        // `internalNote`). Pasarle texto plano tira SyntaxError en el render de
        // OWL y deja el POS en blanco.
        const note = JSON.stringify([{ text: inst.name, colorIndex: 0 }]);
        const newLine = await this.props.pos.addLineToCurrentOrder(
            {
                product_tmpl_id: product.product_tmpl_id || product,
                product_id: product,
                qty: 1,
                price_unit: priceUnit,
                note: note,
            },
            {},
            false
        );

        // Subimos el amount del payment line para que cubra la nueva línea.
        // Usamos el priceIncl del accounting recién calculado por Odoo.
        const lineIncl =
            (newLine && (newLine.priceIncl || newLine.price_subtotal_incl)) || diffAmount;
        this.props.line.amount = this.state.rawAmount + lineIncl;
        this.props.line.card_installment_pos_id = inst.id;
        return this.execButton(this.props.confirm);
    }

    _showMsg(msg, title) {
        this.env.services.dialog.add(AlertDialog, {
            title: title,
            body: msg,
        });
    }
}
