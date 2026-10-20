import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import { registry } from "@web/core/registry";

function openCashMove() {
    return Chrome.clickMenuOption("Cash In/Out");
}

function enterAmount(amount) {
    return {
        content: `Enter the amount ${amount}`,
        trigger: ".modal input.o_input",
        run: `edit ${amount}`,
    };
}

function selectReason(name) {
    return {
        content: `Select reason ${name}`,
        trigger: ".modal select.trx-cash-reason",
        run: `selectByLabel ${name}`,
    };
}

function confirmDisabled() {
    return {
        content: "Confirm is disabled until a reason is selected",
        trigger: ".modal .modal-footer button.confirm:disabled",
    };
}

registry.category("web_tour.tours").add("trx_cash_move_reason_tour", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            // Cash out: the reason is required, free text alone is not enough.
            openCashMove(),
            {
                content: "Cash out is the default type",
                trigger: ".modal .input-type.btn-danger:contains(Cash Out)",
            },
            enterAmount("120"),
            Chrome.fillTextArea(".cash-reason", "Sin motivo"),
            confirmDisabled(),
            {
                content: "Only cash-out reasons are offered",
                trigger: ".modal select.trx-cash-reason:not(:has(option:contains(Aporte del socio)))",
            },
            selectReason("Gastos menores"),
            {
                content: "The text area becomes an optional note",
                trigger: ".modal .form-floating label[for=reason]:contains(Note (optional))",
            },
            Chrome.fillTextArea(".cash-reason", "Librería"),
            Dialog.confirm(),
            // Cash in with a reason and without note.
            openCashMove(),
            {
                content: "Switch to cash in",
                trigger: ".modal .input-type:contains(Cash In)",
                run: "click",
            },
            enterAmount("300"),
            {
                content: "Only cash-in reasons are offered",
                trigger: ".modal select.trx-cash-reason:not(:has(option:contains(Gastos menores)))",
            },
            selectReason("Aporte del socio"),
            Dialog.confirm(),
        ].flat(),
});
