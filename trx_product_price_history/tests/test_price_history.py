# Part of trx_product_price_history. Author: Trixocom. License: LGPL-3.
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPriceHistory(TransactionCase):
    def setUp(self):
        super().setUp()
        self.History = self.env["trx.product.price.history"]
        self.partner = self.env["res.partner"].create({"name": "QA Proveedor Historial", "supplier_rank": 1})
        self.tmpl = self.env["product.template"].create({
            "name": "QA artículo historial", "type": "consu", "list_price": 1000.0,
        })

    def _rows(self, price_type):
        return self.History.search([("product_tmpl_id", "=", self.tmpl.id), ("price_type", "=", price_type)])

    def test_list_price_change_is_logged(self):
        self.tmpl.list_price = 1100.0
        rows = self._rows("list_price")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.old_value, 1000.0)
        self.assertEqual(rows.new_value, 1100.0)
        self.assertAlmostEqual(rows.variation_pct, 0.10, places=4)
        self.assertEqual(rows.origin, "product")
        self.assertEqual(self.tmpl.trx_pvp_previous, 1000.0)
        # mismo valor: no agrega fila
        self.tmpl.list_price = 1100.0
        self.assertEqual(len(self._rows("list_price")), 1)

    def test_context_origin_and_skip(self):
        self.tmpl.with_context(
            trx_price_history_origin="revision", trx_price_history_ref="LP/TEST", trx_price_history_reason="Lista nueva"
        ).write({"list_price": 1200.0})
        row = self._rows("list_price")
        self.assertEqual(row.origin, "revision")
        self.assertEqual(row.origin_ref, "LP/TEST")
        self.assertEqual(row.reason, "Lista nueva")
        self.tmpl.with_context(trx_price_history_skip=True).write({"list_price": 1300.0})
        self.assertEqual(len(self._rows("list_price")), 1)

    def test_supplierinfo_logged(self):
        seller = self.env["product.supplierinfo"].create({
            "partner_id": self.partner.id, "product_tmpl_id": self.tmpl.id, "price": 500.0, "product_code": "QA1",
        })
        rows = self._rows("supplier_price")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.new_value, 500.0)
        self.assertEqual(rows.partner_id, self.partner)
        seller.price = 550.0
        rows = self._rows("supplier_price")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].old_value, 500.0)
        self.assertEqual(rows[0].new_value, 550.0)

    def test_standard_price_logged_per_company(self):
        product = self.tmpl.product_variant_id
        product.standard_price = 400.0
        rows = self._rows("standard_price")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.company_id, self.env.company)
        self.assertEqual(rows.new_value, 400.0)
