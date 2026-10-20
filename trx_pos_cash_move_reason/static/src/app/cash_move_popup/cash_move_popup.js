import { CashMovePopup } from "@point_of_sale/app/components/popups/cash_move_popup/cash_move_popup";
import { patch } from "@web/core/utils/patch";

patch(CashMovePopup.prototype, {
    setup() {
        super.setup();
        this.state.trxReasonId = "";
    },

    /** Reasons loaded for this PoS that apply to the selected kind of move. */
    get trxReasons() {
        const isIn = this.state.type === "in";
        return this.pos.models["pos.cash.move.reason"]
            .getAll()
            .filter((reason) => (isIn ? reason.is_income_reason : reason.is_expense_reason))
            .sort((a, b) => a.sequence - b.sequence || a.name.localeCompare(b.name) || a.id - b.id);
    },

    get trxSelectedReason() {
        if (!this.state.trxReasonId) {
            return null;
        }
        return this.trxReasons.find((reason) => String(reason.id) === String(this.state.trxReasonId)) || null;
    },

    get trxReasonRequired() {
        return Boolean(this.pos.config.trx_cash_reason_required) && this.trxReasons.length > 0;
    },

    onClickButton(type) {
        super.onClickButton(type);
        this.state.trxReasonId = "";
    },

    isValidCashMove() {
        if (this.trxSelectedReason) {
            return this.env.utils.isValidFloat(this.state.amount);
        }
        if (this.trxReasonRequired) {
            return false;
        }
        return super.isValidCashMove();
    },

    async confirm() {
        const reason = this.trxSelectedReason;
        if (reason) {
            // The label ends up in the statement line, the cash moves list and the receipt.
            const note = this.state.reason.trim();
            this.state.reason = note ? `${reason.name} - ${note}` : reason.name;
        }
        return await super.confirm(...arguments);
    },

    _prepareTryCashInOutPayload() {
        const result = super._prepareTryCashInOutPayload(...arguments);
        const reason = this.trxSelectedReason;
        if (reason) {
            const last = result.length - 1;
            result[last] = { ...result[last], trx_cash_reason_id: reason.id };
        }
        return result;
    },
});
