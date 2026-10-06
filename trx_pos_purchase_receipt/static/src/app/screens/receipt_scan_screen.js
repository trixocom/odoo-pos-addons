// Part of trx_pos_purchase_receipt. Author: Trixocom. License: LGPL-3.
import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useBarcodeReader } from "@point_of_sale/app/hooks/barcode_reader_hook";
import { ask, makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { deserializeDateTime, formatDate } from "@web/core/l10n/dates";
import { TrxShortageDialog } from "../components/shortage_dialog";
import { trxFormatQty } from "./receipt_list_screen";

const SAVE_DELAY_MS = 800;
// Todos los tipos que puede devolver la nomenclatura: en esta pantalla cualquier
// lectura es un código de artículo.
const BARCODE_TYPES = [
    "product",
    "weight",
    "price",
    "discount",
    "client",
    "cashier",
    "location",
    "lot",
    "package",
    "coupon",
    "alias",
    "error",
];

function round4(value) {
    return Math.round(value * 10000) / 10000;
}

export class TrxReceiptScanScreen extends Component {
    static template = "trx_pos_purchase_receipt.TrxReceiptScanScreen";
    static props = { pickingId: Number };
    static storeOnOrder = false;

    setup() {
        this.pos = usePos();
        this.ui = useService("ui");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.inputRef = useRef("codeInput");
        this.formatQty = trxFormatQty;
        this.state = useState({
            loading: true,
            data: null,
            lines: [],
            lastMoveId: null,
            code: "",
            dirty: false,
            saving: false,
            saveError: false,
            validating: false,
        });
        const cbMap = {};
        for (const type of BARCODE_TYPES) {
            cbMap[type] = (parsed) => this.onScan(parsed.code);
        }
        cbMap.gs1 = (elements) => {
            const product = elements.find((e) => e.type === "product");
            this.onScan(product ? product.value : elements[0]?.code);
        };
        useBarcodeReader(cbMap, true);
        onMounted(() => this.load());
        onWillUnmount(() => {
            clearTimeout(this.saveTimer);
            if (this.state.dirty) {
                this.save();
            }
        });
    }

    // ------------------------------------------------------------------
    // Datos
    // ------------------------------------------------------------------
    async load() {
        this.state.loading = true;
        const data = await this.pos.trxReceiptCall("trx_pos_receipt_load", [this.props.pickingId]);
        this.state.loading = false;
        if (!data) {
            this.goToList();
            return;
        }
        this.state.data = data;
        this.state.lines = data.lines;
        this.focusInput();
    }

    get blind() {
        return Boolean(this.state.data?.blind);
    }

    get totalScanned() {
        return round4(this.state.lines.reduce((s, l) => s + (l.scanned || 0), 0));
    }

    get totalDemand() {
        return round4(this.state.lines.reduce((s, l) => s + (l.demand || 0), 0));
    }

    get progressPct() {
        if (this.blind || !this.totalDemand) {
            return 0;
        }
        return Math.min(100, Math.round((this.totalScanned / this.totalDemand) * 100));
    }

    formatDate(value) {
        return value ? formatDate(deserializeDateTime(value)) : "";
    }

    lineClass(line) {
        return {
            "trx-line-last": line.move_id === this.state.lastMoveId,
            "trx-line-done": !this.blind && line.scanned > 0 && line.scanned === line.demand,
            "trx-line-over": !this.blind && line.scanned > line.demand,
        };
    }

    lineLabel(line) {
        return line.default_code ? `[${line.default_code}] ${line.name}` : line.name;
    }

    // ------------------------------------------------------------------
    // Escaneo
    // ------------------------------------------------------------------
    focusInput() {
        if (!this.ui.isSmall) {
            setTimeout(() => this.inputRef.el?.focus(), 50);
        }
    }

    findLine(code) {
        const c = String(code || "").trim().toLowerCase();
        if (!c) {
            return null;
        }
        const has = (list) => (list || []).some((x) => String(x).trim().toLowerCase() === c);
        let matches = this.state.lines.filter((l) => has(l.codes));
        if (!matches.length) {
            // Código de otro proveedor: solo si identifica un único artículo de la recepción
            const others = this.state.lines.filter((l) => has(l.other_codes));
            if (others.length && new Set(others.map((l) => l.product_id)).size === 1) {
                matches = others;
            }
        }
        if (!matches.length) {
            return null;
        }
        if (!this.blind) {
            const pending = matches.find((l) => l.scanned < l.demand);
            if (pending) {
                return pending;
            }
        }
        return matches[0];
    }

    async onScan(code) {
        code = String(code || "").trim();
        if (!code || !this.state.data || this.state.validating) {
            return;
        }
        const line = this.findLine(code);
        if (!line) {
            const name = await this.pos.trxReceiptCall("trx_pos_receipt_identify", [code], {}, { silent: true });
            this.notification.add(
                name
                    ? _t("%s no está en esta recepción.", name)
                    : _t("El código %s no corresponde a ningún artículo de esta recepción.", code),
                { type: "danger", title: _t("Artículo no pedido") }
            );
            return;
        }
        this.setQty(line, round4((line.scanned || 0) + 1));
    }

    onSubmitCode(ev) {
        ev.preventDefault();
        const code = this.inputRef.el?.value || this.state.code;
        this.state.code = "";
        if (this.inputRef.el) {
            this.inputRef.el.value = "";
        }
        this.onScan(code);
    }

    setQty(line, qty) {
        if (line.tracking) {
            this.dialog.add(AlertDialog, {
                title: _t("Artículo con lote o número de serie"),
                body: _t("%s se recibe desde el backend (Inventario).", this.lineLabel(line)),
            });
            return;
        }
        const before = line.scanned || 0;
        if (!this.blind && this.state.data.block_over && round4(qty) > line.demand) {
            this.notification.add(
                _t("%(item)s: no se puede recibir más de lo pedido (%(qty)s).", {
                    item: this.lineLabel(line),
                    qty: trxFormatQty(line.demand),
                }),
                { type: "danger", title: _t("Cantidad mayor a la pedida") }
            );
            return;
        }
        line.scanned = Math.max(0, round4(qty));
        this.state.lastMoveId = line.move_id;
        if (!this.blind && line.scanned > line.demand && before <= line.demand) {
            this.notification.add(_t("%s: se está recibiendo más de lo pedido.", this.lineLabel(line)), {
                type: "warning",
            });
        }
        this.scheduleSave();
        const el = document.querySelector(`.trx-line[data-move-id="${line.move_id}"]`);
        el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }

    increment(line, delta) {
        this.setQty(line, (line.scanned || 0) + delta);
        this.focusInput();
    }

    async editQty(line) {
        const value = await makeAwaitable(this.dialog, NumberPopup, {
            title: this.lineLabel(line),
            subtitle: this.blind ? "" : _t("Pedido: %s", trxFormatQty(line.demand)),
            startingValue: line.scanned ? String(line.scanned) : "",
            confirmButtonLabel: _t("Aplicar"),
        });
        if (value === undefined || value === null || value === "") {
            this.focusInput();
            return;
        }
        const qty = parseFloat(String(value).replace(",", "."));
        if (!isNaN(qty) && qty >= 0) {
            this.setQty(line, qty);
        }
        this.focusInput();
    }

    // ------------------------------------------------------------------
    // Guardado del avance
    // ------------------------------------------------------------------
    quantities() {
        return Object.fromEntries(this.state.lines.map((l) => [l.move_id, l.scanned || 0]));
    }

    scheduleSave() {
        this.state.dirty = true;
        clearTimeout(this.saveTimer);
        this.saveTimer = setTimeout(() => this.save(), SAVE_DELAY_MS);
    }

    async save() {
        clearTimeout(this.saveTimer);
        if (!this.state.data) {
            return true;
        }
        this.state.saving = true;
        this.state.dirty = false;
        const res = await this.pos.trxReceiptCall(
            "trx_pos_receipt_save",
            [this.state.data.id, this.quantities()],
            {},
            { silent: true }
        );
        this.state.saving = false;
        this.state.saveError = res === undefined;
        if (res === undefined) {
            this.state.dirty = true;
        }
        return res !== undefined;
    }

    // ------------------------------------------------------------------
    // Validación
    // ------------------------------------------------------------------
    diffRows(filter) {
        return this.state.lines.filter(filter).map((l) => ({
            move_id: l.move_id,
            label: this.lineLabel(l),
            demandStr: trxFormatQty(l.demand),
            scannedStr: trxFormatQty(l.scanned || 0),
            diffStr: trxFormatQty(round4((l.demand || 0) - (l.scanned || 0))),
        }));
    }

    async validate() {
        if (this.state.validating || !this.state.data) {
            return;
        }
        if (!this.totalScanned) {
            this.dialog.add(AlertDialog, {
                title: _t("Recepción vacía"),
                body: _t("Todavía no se escaneó ningún artículo."),
            });
            return;
        }
        let shortage = null;
        if (this.blind) {
            const ok = await ask(this.dialog, {
                title: _t("Confirmar recepción"),
                body: _t(
                    "Se van a ingresar %s unidades escaneadas. Lo que no llegó queda pendiente.",
                    trxFormatQty(this.totalScanned)
                ),
                confirmLabel: _t("Validar recepción"),
                cancelLabel: _t("Seguir escaneando"),
            });
            if (!ok) {
                return this.focusInput();
            }
        } else {
            const short = this.diffRows((l) => (l.scanned || 0) < l.demand);
            const over = this.diffRows((l) => (l.scanned || 0) > l.demand);
            if (short.length) {
                shortage = await makeAwaitable(this.dialog, TrxShortageDialog, {
                    title: _t("Faltan artículos"),
                    policy: this.state.data.backorder_policy || "ask",
                    shortLines: short,
                    overLines: over,
                });
                if (!shortage) {
                    return this.focusInput();
                }
            } else {
                const body = over.length
                    ? _t("Se recibe MÁS de lo pedido en:\n%s\n\n¿Confirmás la recepción?",
                          over.map((l) => `• ${l.label}: pedido ${l.demandStr}, recibido ${l.scannedStr}`).join("\n"))
                    : _t("Se recibió todo lo pedido. ¿Validar la recepción?");
                const ok = await ask(this.dialog, {
                    title: _t("Confirmar recepción"),
                    body,
                    confirmLabel: _t("Validar recepción"),
                    cancelLabel: _t("Seguir escaneando"),
                });
                if (!ok) {
                    return this.focusInput();
                }
            }
        }
        this.state.validating = true;
        clearTimeout(this.saveTimer);
        const res = await this.pos.trxReceiptCall("trx_pos_receipt_validate", [
            this.state.data.id,
            this.quantities(),
            shortage,
            this.pos.getCashier()?.name || null,
        ]);
        this.state.validating = false;
        if (!res) {
            return;
        }
        this.state.dirty = false;
        let msg = _t("%s ingresada al stock.", res.name);
        if (res.backorder) {
            msg += " " + _t("Lo faltante quedó pendiente en %s.", res.backorder);
        }
        this.notification.add(msg, { type: "success", title: _t("Recepción validada") });
        this.pos.trxRefreshReceiptCount();
        this.goToList();
    }

    async goToList() {
        if (this.state.dirty) {
            await this.save();
        }
        this.pos.navigate("TrxReceiptListScreen");
    }
}

registry.category("pos_pages").add("TrxReceiptScanScreen", {
    name: "TrxReceiptScanScreen",
    component: TrxReceiptScanScreen,
    route: `/pos/ui/${odoo.pos_config_id}/trx_receipt/{int:pickingId}`,
    params: { pickingId: true },
});
