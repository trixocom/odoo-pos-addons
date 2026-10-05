from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSupplierCode(TransactionCase):
    def test_codes_and_search(self):
        sup1 = self.env["res.partner"].create({"name": "QA Proveedor 1"})
        sup2 = self.env["res.partner"].create({"name": "QA Proveedor 2"})
        tmpl = self.env["product.template"].create({
            "name": "QA Juego de mesa", "default_code": "QA-ALFA-1", "barcode": "7790000999991",
            "seller_ids": [
                (0, 0, {"partner_id": sup1.id, "product_code": "SUP1-XYZ", "price": 100}),
                (0, 0, {"partner_id": sup2.id, "product_code": "DA-77120", "price": 90}),
            ],
        })
        self.assertEqual(set(tmpl.trx_supplier_codes.split()), {"SUP1-XYZ", "DA-77120"})
        self.assertIn(tmpl, self.env["product.template"].search([("display_name", "ilike", "DA-77120")]))
        self.assertIn(tmpl.product_variant_id, self.env["product.product"].search([("display_name", "ilike", "SUP1-XYZ")]))
        self.assertIn("trx_supplier_codes", self.env["product.template"]._load_pos_data_fields(False))
        tmpl.seller_ids.filtered(lambda s: s.partner_id == sup1).product_code = "SUP1-NEW"
        self.assertEqual(set(tmpl.trx_supplier_codes.split()), {"SUP1-NEW", "DA-77120"})
