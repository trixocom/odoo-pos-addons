/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { normalize } from "@web/core/l10n/utils";
import { ProductTemplate } from "@point_of_sale/app/models/product_template";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";

// Búsqueda local: los códigos de proveedor se suman al texto buscable del producto
patch(ProductTemplate.prototype, {
    get searchString() {
        const base = super.searchString;
        const codes = this.trx_supplier_codes ? normalize(this.trx_supplier_codes) : "";
        return codes ? `${base} ${codes}` : base;
    },
});

// Búsqueda en el servidor (productos que no están cargados en el POS)
patch(ProductScreen.prototype, {
    loadProductFromDBDomain(searchProductWord) {
        const domain = super.loadProductFromDBDomain(...arguments);
        return ["|", ["trx_supplier_codes", "ilike", searchProductWord], ...domain];
    },
});
