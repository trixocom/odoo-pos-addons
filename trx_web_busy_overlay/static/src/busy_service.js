/** @odoo-module **/
// Part of trx_web_busy_overlay. Author: Trixocom. License: LGPL-3.
import { registry } from "@web/core/registry";
import { reactive } from "@odoo/owl";

/**
 * Servicio `trx_busy`: estado reactivo del overlay de proceso.
 *   show(title, {subtitle, icon, phases})  → muestra
 *   hide()                                 → oculta
 *   run(fn, title, options)                → muestra, ejecuta fn() (promesa) y oculta al terminar (también si falla)
 */
export const busyService = {
    start() {
        const state = reactive({
            visible: false,
            title: "",
            subtitle: "",
            icon: "fa-magic",
            phases: [],
            startedAt: 0,
            count: 0,
        });
        let depth = 0;
        function show(title, options = {}) {
            depth += 1;
            Object.assign(state, {
                visible: true,
                title: title || "Procesando…",
                subtitle: options.subtitle || "",
                icon: options.icon || "fa-magic",
                phases: options.phases || [],
                startedAt: state.visible && depth > 1 ? state.startedAt : Date.now(),
                count: state.count + 1,
            });
        }
        function hide() {
            depth = Math.max(0, depth - 1);
            if (depth === 0) {
                state.visible = false;
            }
        }
        async function run(fn, title, options = {}) {
            show(title, options);
            try {
                return await fn();
            } finally {
                hide();
            }
        }
        return { state, show, hide, run };
    },
};
registry.category("services").add("trx_busy", busyService);

// Botones de vista: context={'trx_busy': 'Título', 'trx_busy_sub': 'Detalle', 'trx_busy_icon': 'fa-cloud-upload'}
const actionServiceDef = registry.category("services").get("action");
const originalStart = actionServiceDef.start;
actionServiceDef.start = function (env, deps) {
    const service = originalStart.call(this, env, deps);
    const originalDoActionButton = service.doActionButton;
    service.doActionButton = async function (params, options) {
        const ctx = params && params.buttonContext;
        const title = ctx && ctx.trx_busy;
        if (!title) {
            return originalDoActionButton.call(this, params, options);
        }
        const busyOptions = {
            subtitle: ctx.trx_busy_sub || "",
            icon: ctx.trx_busy_icon || "fa-magic",
            phases: Array.isArray(ctx.trx_busy_phases) ? ctx.trx_busy_phases : [],
        };
        for (const key of ["trx_busy", "trx_busy_sub", "trx_busy_icon", "trx_busy_phases"]) {
            delete ctx[key];
        }
        const busy = env.services.trx_busy;
        return busy.run(() => originalDoActionButton.call(this, params, options), title, busyOptions);
    };
    return service;
};
