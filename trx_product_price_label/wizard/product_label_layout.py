# Part of trx_product_price_label. Author: Trixocom. License: LGPL-3.
from odoo import api, fields, models

TRX_FORMATS = {
    # formato: (xml_id del reporte, columnas, filas)
    "trx_thermal": ("trx_product_price_label.report_price_label_thermal", 1, 1),
    "trx_sheet": ("trx_product_price_label.report_price_label_sheet", 3, 8),
}


class ProductLabelLayout(models.TransientModel):
    _inherit = "product.label.layout"

    print_format = fields.Selection(
        selection_add=[
            ("trx_thermal", "Etiqueta de precio térmica 50 x 25 mm"),
            ("trx_sheet", "Etiquetas de precio hoja A4 3 x 8 (70 x 37 mm)"),
        ],
        ondelete={"trx_thermal": "set default", "trx_sheet": "set default"},
    )

    @api.depends("print_format")
    def _compute_dimensions(self):
        trx = self.filtered(lambda w: w.print_format in TRX_FORMATS)
        for wizard in trx:
            _xml, wizard.columns, wizard.rows = TRX_FORMATS[wizard.print_format]
        return super(ProductLabelLayout, self - trx)._compute_dimensions()

    def _prepare_report_data(self):
        xml_id, data = super()._prepare_report_data()
        if self.print_format in TRX_FORMATS:
            xml_id = TRX_FORMATS[self.print_format][0]
            data["price_included"] = True
        return xml_id, data
