/** @odoo-module **/
// Part of trx_web_busy_overlay. Author: Trixocom. License: LGPL-3.
import { Component, useState, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class TrxBusyOverlay extends Component {
    static template = "trx_web_busy_overlay.Overlay";
    static props = {};

    setup() {
        this.busy = useService("trx_busy");
        this.state = useState(this.busy.state);
        this.clock = useState({ seconds: 0 });
        this.timer = setInterval(() => {
            if (this.state.visible) {
                this.clock.seconds = Math.floor((Date.now() - this.state.startedAt) / 1000);
            }
        }, 500);
        onWillUnmount(() => clearInterval(this.timer));
    }

    get elapsed() {
        const s = this.clock.seconds;
        return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
    }

    get phase() {
        const phases = this.state.phases || [];
        if (!phases.length) {
            return "";
        }
        return phases[Math.min(Math.floor(this.clock.seconds / 6), phases.length - 1)];
    }
}

registry.category("main_components").add("TrxBusyOverlay", { Component: TrxBusyOverlay });
