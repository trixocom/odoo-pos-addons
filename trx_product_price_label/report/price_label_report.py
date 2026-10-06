# Part of trx_product_price_label. Author: Trixocom. License: LGPL-3.
from odoo import api, models
from odoo.addons.product.report.product_label_report import _prepare_data
from odoo.tools.misc import formatLang

SHEET_PER_PAGE = 24


class TrxPriceLabelMixin(models.AbstractModel):
    _name = "trx.price.label.mixin"
    _description = "Datos comunes de las etiquetas de precio"

    @api.model
    def _trx_format_price(self, amount, currency):
        """$ 21.780 (sin decimales si son cero) o $ 21.780,50."""
        if currency.is_zero(amount - round(amount)):
            return formatLang(self.env, amount, currency_obj=currency, rounding_unit="units")
        return formatLang(self.env, amount, currency_obj=currency)

    @api.model
    def _trx_label_prices(self, product, pricelist):
        """Precio final con impuestos y precio sin impuestos nacionales (IVA e internos)."""
        company = self.env.company
        currency = pricelist.currency_id if pricelist else company.currency_id
        variant = product if product._name == "product.product" else product.product_variant_id
        if pricelist:
            base = pricelist._get_product_price(variant, 1.0, currency=currency)
        else:
            base = variant.lst_price
        taxes = product.taxes_id._filter_taxes_by_company(company)
        if taxes:
            res = taxes.compute_all(base, currency=currency, quantity=1.0, product=variant)
            final, without = res["total_included"], res["total_excluded"]
        else:
            final = without = base
        return currency, final, without

    @api.model
    def _trx_labels(self, docids, data):
        # Por la acción de reporte los datos llegan serializados en JSON (claves str);
        # llamado desde Python pueden venir con claves int.
        data = dict(data or {})
        for key in ("quantity_by_product", "custom_barcodes"):
            if data.get(key):
                data[key] = {str(k): v for k, v in data[key].items()}
        values = _prepare_data(self.env, docids, data)
        pricelist = values.get("pricelist")
        labels = []
        # _prepare_data ordena por nombre descendente (lo usa con popitem); acá se invierte
        for product, barcodes in reversed(list((values.get("quantity") or {}).items())):
            currency, final, without = self._trx_label_prices(product, pricelist)
            for barcode, qty in barcodes:
                price = self._trx_format_price(final, currency)
                label = {
                    "name": product.display_name if product._name == "product.product" else product.name,
                    "code": product.default_code or "",
                    "barcode": barcode or "",
                    "price": price,
                    "price_long": len(price) > 9,
                    "price_without_taxes": formatLang(self.env, without, currency_obj=currency),
                }
                labels.extend([label] * int(qty or 0))
        values["labels"] = labels
        values["pages"] = [labels[i : i + SHEET_PER_PAGE] for i in range(0, len(labels), SHEET_PER_PAGE)]
        return values


class ReportPriceLabelThermal(models.AbstractModel):
    _name = "report.trx_product_price_label.report_price_label_thermal_doc"
    _inherit = "trx.price.label.mixin"
    _description = "Etiqueta de precio térmica"

    def _get_report_values(self, docids, data):
        return self._trx_labels(docids, data)


class ReportPriceLabelSheet(models.AbstractModel):
    _name = "report.trx_product_price_label.report_price_label_sheet_doc"
    _inherit = "trx.price.label.mixin"
    _description = "Etiquetas de precio hoja A4"

    def _get_report_values(self, docids, data):
        return self._trx_labels(docids, data)
