// Part of trx_pos_purchase_receipt. Author: Trixocom. License: LGPL-3.
import { patch } from "@web/core/utils/patch";
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";

export const TRX_RECEIPT_SCREENS = ["TrxReceiptListScreen", "TrxReceiptScanScreen"];

patch(Navbar.prototype, {
    get mainButton() {
        if (TRX_RECEIPT_SCREENS.includes(this.pos.router.state.current)) {
            return "trx_receipt";
        }
        return super.mainButton;
    },
    onClickTrxReceipts() {
        this.pos.navigate("TrxReceiptListScreen");
    },
});
