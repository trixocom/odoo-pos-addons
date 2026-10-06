// Part of trx_pos_purchase_receipt. Author: Trixocom. License: LGPL-3.
import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class TrxShortageDialog extends Component {
    static template = "trx_pos_purchase_receipt.TrxShortageDialog";
    static components = { Dialog };
    static props = {
        title: String,
        shortLines: Array,
        overLines: { type: Array, optional: true },
        policy: { type: String, optional: true },
        getPayload: Function,
        close: Function,
    };

    choose(value) {
        this.props.getPayload(value);
        this.props.close();
    }
}
