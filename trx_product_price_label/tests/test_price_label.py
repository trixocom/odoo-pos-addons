# Part of trx_product_price_label. Author: Trixocom. License: LGPL-3.
import re

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPriceLabel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        cls.tax = cls.env["account.tax"].create(
            {
                "name": "TEST IVA 21% incluido",
                "amount": 21,
                "type_tax_use": "sale",
                "price_include_override": "tax_included",
                "company_id": company.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "TEST ETQ Rompecabezas 48 piezas",
                "default_code": "TETQ-001",
                "barcode": "7790000099998",
                "list_price": 21780,
                "taxes_id": [(6, 0, cls.tax.ids)],
            }
        )

    def _render(self, print_format, qty=2):
        wizard = self.env["product.label.layout"].create(
            {"print_format": print_format, "custom_quantity": qty, "product_ids": [(6, 0, self.product.ids)]}
        )
        xml_id, data = wizard._prepare_report_data()
        report = self.env.ref(xml_id)
        html = self.env["ir.actions.report"]._render_qweb_html(report.report_name, self.product.ids, data=data)[0]
        return wizard, xml_id, html.decode()

    def test_thermal(self):
        wizard, xml_id, html = self._render("trx_thermal", 3)
        self.assertEqual(xml_id, "trx_product_price_label.report_price_label_thermal")
        self.assertEqual((wizard.columns, wizard.rows), (1, 1))
        self.assertEqual(html.count('class="trx-pl"'), 3)
        self.assertEqual(html.count('class="article"'), 3)
        self.assertIn("TETQ-001", html)
        self.assertTrue(re.search(r"21[.,]780", html))
        self.assertIn("Precio sin impuestos nacionales", html)
        self.assertTrue(re.search(r"18[.,]000", html))
        self.assertIn("data:image/png;base64", html)

    def test_sheet(self):
        wizard, xml_id, html = self._render("trx_sheet", 25)
        self.assertEqual((wizard.columns, wizard.rows), (3, 8))
        self.assertEqual(html.count('class="trx-pl"'), 25)
        # 25 etiquetas = 2 hojas (un .article por hoja)
        self.assertEqual(html.count('class="article"'), 2)

    def test_native_formats_untouched(self):
        wizard = self.env["product.label.layout"].create(
            {"print_format": "4x12", "product_ids": [(6, 0, self.product.ids)]}
        )
        self.assertEqual((wizard.columns, wizard.rows), (4, 12))
        xml_id, _data = wizard._prepare_report_data()
        self.assertEqual(xml_id, "product.report_product_template_label_4x12_noprice")
