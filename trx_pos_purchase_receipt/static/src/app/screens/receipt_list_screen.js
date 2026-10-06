// Part of trx_pos_purchase_receipt. Author: Trixocom. License: LGPL-3.
import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { deserializeDateTime, formatDate } from "@web/core/l10n/dates";
import { normalize } from "@web/core/l10n/utils";

export function trxFormatQty(qty) {
    if (qty === false || qty === null || qty === undefined) {
        return "";
    }
    return Number.isInteger(qty) ? String(qty) : qty.toFixed(2).replace(/\.?0+$/, "");
}

export class TrxReceiptListScreen extends Component {
    static template = "trx_pos_purchase_receipt.TrxReceiptListScreen";
    static props = {};
    static storeOnOrder = false;

    setup() {
        this.pos = usePos();
        this.ui = useService("ui");
        this.state = useState({ loading: true, receipts: [], search: "" });
        this.formatQty = trxFormatQty;
        onMounted(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const receipts = await this.pos.trxReceiptCall("trx_pos_receipt_pending");
        if (receipts) {
            this.state.receipts = receipts;
            this.pos.trxReceiptCount = receipts.length;
        }
        this.state.loading = false;
    }

    get filteredReceipts() {
        const words = normalize(this.state.search || "").split(/\s+/).filter(Boolean);
        if (!words.length) {
            return this.state.receipts;
        }
        return this.state.receipts.filter((r) => {
            const text = normalize([r.name, r.purchase, r.partner, r.partner_ref].join(" "));
            return words.every((w) => text.includes(w));
        });
    }

    formatDate(value) {
        return value ? formatDate(deserializeDateTime(value)) : "";
    }

    open(receipt) {
        this.pos.navigate("TrxReceiptScanScreen", { pickingId: receipt.id });
    }

    back() {
        const order = this.pos.getOrder() || this.pos.addNewOrder();
        this.pos.navigateToOrderScreen(order);
    }
}

registry.category("pos_pages").add("TrxReceiptListScreen", {
    name: "TrxReceiptListScreen",
    component: TrxReceiptListScreen,
    route: `/pos/ui/${odoo.pos_config_id}/trx_receipts`,
    params: {},
});
