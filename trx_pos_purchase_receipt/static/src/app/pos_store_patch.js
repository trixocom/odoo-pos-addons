// Part of trx_pos_purchase_receipt. Author: Trixocom. License: LGPL-3.
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const REFRESH_MS = 5 * 60 * 1000;

patch(PosStore.prototype, {
    async afterProcessServerData() {
        const res = await super.afterProcessServerData(...arguments);
        this.trxReceiptCount = 0;
        if (this.config.trx_receipt_allowed) {
            this.trxRefreshReceiptCount();
            setInterval(() => this.trxRefreshReceiptCount(), REFRESH_MS);
        }
        return res;
    },

    /** Llamada al servidor para la recepción; muestra el error y devuelve undefined si falla. */
    async trxReceiptCall(method, args = [], kwargs = {}, { silent = false } = {}) {
        try {
            return await this.data.call("stock.picking", method, [this.config.id, ...args], kwargs);
        } catch (error) {
            if (!silent) {
                const message =
                    error?.data?.message ||
                    error?.message ||
                    _t("No se pudo comunicar con el servidor. Revisá la conexión.");
                this.dialog.add(AlertDialog, { title: _t("Recepción de mercadería"), body: message });
            }
            return undefined;
        }
    },

    async trxRefreshReceiptCount() {
        if (!this.config.trx_receipt_allowed || this.data.network?.offline) {
            return;
        }
        const count = await this.trxReceiptCall("trx_pos_receipt_count", [], {}, { silent: true });
        if (count !== undefined) {
            this.trxReceiptCount = count;
        }
    },
});
