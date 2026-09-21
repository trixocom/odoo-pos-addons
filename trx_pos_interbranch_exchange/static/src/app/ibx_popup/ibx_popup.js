/** @odoo-module */
import { useState, useRef, onMounted } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog, ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

/**
 * Popup del cambio inter-sucursal (Trixocom).
 *
 * 1. El cajero escanea/tipea el código (uuid o número de la venta original).
 * 2. `ibx_lookup` devuelve la venta original y la elegibilidad de cada línea.
 * 3. El cajero elige productos/cantidades.
 * 4. Al confirmar, `ibx_prepare` crea el cambio (draft) y devuelve el importe,
 *    que se aplica al payment line. El servidor ejecuta el resto al confirmar
 *    la venta nueva.
 */
export class IbxExchangePopup extends ConfirmationDialog {
    static template = "trx_pos_interbranch_exchange.IbxExchangePopup";
    static props = {
        ...ConfirmationDialog.props,
        line: Object,
        order: Object,
        pos: Object,
        maxAmount: Number,
        allowCashDifference: Boolean,
    };
    static defaultProps = {
        ...ConfirmationDialog.defaultProps,
        confirmLabel: _t("Aplicar cambio"),
        cancelLabel: _t("Cancelar"),
        title: _t("Cambio inter-sucursal"),
    };

    setup() {
        super.setup();
        this.orm = this.env.services.orm;
        this.codeInput = useRef("ibxCode");
        this.state = useState({
            code: "",
            loading: false,
            error: "",
            result: null, // {order, lines}
            selected: {}, // origin_line_id -> qty
        });
        onMounted(() => {
            if (this.codeInput.el) {
                this.codeInput.el.focus();
            }
        });
    }

    formatCurrency(amount) {
        return this.env.utils.formatCurrency(amount || 0);
    }

    get eligibleLines() {
        return (this.state.result?.lines || []).filter((l) => l.eligible);
    }

    get ineligibleLines() {
        return (this.state.result?.lines || []).filter((l) => !l.eligible);
    }

    get selectedAmount() {
        let total = 0;
        for (const l of this.eligibleLines) {
            const qty = parseFloat(this.state.selected[l.origin_line_id] || 0);
            if (qty > 0) {
                total += qty * l.unit_price_incl;
            }
        }
        return Math.round(total * 100) / 100;
    }

    get exceedsMax() {
        return !this.props.allowCashDifference && this.selectedAmount > this.props.maxAmount + 0.005;
    }

    async onCodeKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            await this.lookup();
        }
    }

    async lookup() {
        const code = (this.state.code || "").trim();
        if (!code) {
            return;
        }
        this.state.loading = true;
        this.state.error = "";
        this.state.result = null;
        this.state.selected = {};
        try {
            const res = await this.orm.call("trx.ibx.exchange", "ibx_lookup", [code, this.props.pos.config.id]);
            if (!res.ok) {
                this.state.error = res.error || _t("No se pudo buscar la venta.");
                return;
            }
            this.state.result = res;
            // Por defecto se preselecciona todo lo elegible con su cantidad disponible
            for (const l of res.lines) {
                if (l.eligible) {
                    this.state.selected[l.origin_line_id] = l.qty_available;
                }
            }
        } catch (error) {
            console.error(error);
            this.state.error = (error?.data?.message) || error.message || _t("Error consultando el servidor");
        } finally {
            this.state.loading = false;
        }
    }

    toggleLine(l, ev) {
        if (ev.target.checked) {
            this.state.selected[l.origin_line_id] = l.qty_available;
        } else {
            delete this.state.selected[l.origin_line_id];
        }
    }

    setQty(l, ev) {
        let qty = parseFloat(ev.target.value);
        if (isNaN(qty) || qty <= 0) {
            delete this.state.selected[l.origin_line_id];
            return;
        }
        if (qty > l.qty_available) {
            qty = l.qty_available;
        }
        this.state.selected[l.origin_line_id] = qty;
    }

    async _confirm() {
        if (!this.state.result) {
            this._showMsg(_t("Primero escaneá o tipeá el código del ticket de cambio."), _t("Atención"));
            return false;
        }
        const selectedLines = Object.entries(this.state.selected)
            .filter(([, qty]) => parseFloat(qty) > 0)
            .map(([id, qty]) => ({ origin_line_id: parseInt(id), qty: parseFloat(qty) }));
        if (!selectedLines.length) {
            this._showMsg(_t("Elegí al menos un producto para cambiar."), _t("Atención"));
            return false;
        }
        if (this.exceedsMax) {
            this._showMsg(
                _t("El cambio (%s) supera lo que falta pagar (%s). Agregá productos a la venta hasta cubrir ese importe: no se devuelve diferencia en efectivo.",
                    this.formatCurrency(this.selectedAmount), this.formatCurrency(this.props.maxAmount)),
                _t("Importe del cambio mayor a la compra")
            );
            return false;
        }
        this.state.loading = true;
        try {
            const res = await this.orm.call("trx.ibx.exchange", "ibx_prepare", [
                this.state.code.trim(),
                this.props.pos.config.id,
                selectedLines,
            ]);
            // Campo REAL de pos.payment (ver pos_payment.py): viaja al servidor con la orden.
            this.props.line.trx_ibx_exchange_id = res.exchange_id;
            this.props.line.setAmount(res.amount);
            return this.execButton(this.props.confirm);
        } catch (error) {
            console.error(error);
            this._showMsg((error?.data?.message) || error.message || _t("No se pudo preparar el cambio."), _t("Error"));
            return false;
        } finally {
            this.state.loading = false;
        }
    }

    _showMsg(msg, title) {
        this.env.services.dialog.add(AlertDialog, { title: title, body: msg });
    }
}
