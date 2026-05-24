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
     * Calcula el price_unit (sin impuesto) tal que el total INCLUIDO de la
     * orderline sea exactamente `targetIncl`. En Odoo 18 esto lo hacía
     * `compute_price_force_price_include`, que en 19 ya no existe: usamos
     * el helper de account_tax y ajustamos.
     *
     * @param {number} targetIncl monto con impuestos incluidos (puede ser <0)
     * @param {object} product product.template o product.product del recargo
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
        // Tomamos sólo impuestos no incluidos en precio: son los que suman al
        // total. Los price_include ya están dentro de price_unit.
        const taxesAddingUp = taxes.filter((t) => !t.price_include);
        if (!taxesAddingUp.length) {
            return targetIncl;
        }
        // Probamos con price_unit = targetIncl (asumimos sin impuesto extra),
        // calculamos el total incluido y dividimos por el ratio para corregir.
        const baseLine = accountTaxHelpers.prepare_base_line_for_taxes_computation(
            {},
            {
                tax_ids: taxes,
                quantity: 1,
                price_unit: targetIncl,
                currency_id: this.props.pos.currency,
            }
        );
        accountTaxHelpers.add_tax_details_in_base_line(baseLine, company);
        accountTaxHelpers.round_base_lines_tax_details([baseLine], company);
        const totalIncl = baseLine.tax_details.total_included_currency;
        if (!totalIncl) {
            return targetIncl;
        }
        return (targetIncl * targetIncl) / totalIncl;
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
            this.props.line.cardPlanName = inst.name;
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
        const newLine = await this.props.pos.addLineToCurrentOrder(
            {
                product_tmpl_id: product.product_tmpl_id || product,
                product_id: product,
                qty: 1,
                price_unit: priceUnit,
                note: inst.name,
            },
            {},
            false
        );

        // Subimos el amount del payment line para que cubra la nueva línea.
        // Usamos el priceIncl del accounting recién calculado por Odoo.
        const lineIncl =
            (newLine && (newLine.priceIncl || newLine.price_subtotal_incl)) || diffAmount;
        this.props.line.amount = this.state.rawAmount + lineIncl;
        this.props.line.cardPlanName = inst.name;
        return this.execButton(this.props.confirm);
    }

    _showMsg(msg, title) {
        this.env.services.dialog.add(AlertDialog, {
            title: title,
            body: msg,
        });
    }
}
