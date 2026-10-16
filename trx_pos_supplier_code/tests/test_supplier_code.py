from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSupplierCode(TransactionCase):
    def _ids(self, term, ctx=None):
        Product = self.env["product.product"].with_context(**(ctx or {}))
        return [r[0] for r in Product.name_search(term, limit=10)]

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

    def test_name_search_without_partner(self):
        """Campo Producto de una OC/factura: encuentra por código de proveedor sin saber el proveedor."""
        sup1 = self.env["res.partner"].create({"name": "QA Proveedor A"})
        sup2 = self.env["res.partner"].create({"name": "QA Proveedor B"})
        tmpl = self.env["product.template"].create({
            "name": "QA Rompecabezas de madera", "default_code": "QA-ALFA-2",
            "seller_ids": [
                (0, 0, {"partner_id": sup1.id, "product_code": "QAIMP-4810", "price": 100}),
                (0, 0, {"partner_id": sup2.id, "product_code": "QADA-77120", "price": 108}),
            ],
        })
        vid = tmpl.product_variant_id.id
        self.assertIn(vid, self._ids("QADA-77120"))  # sin proveedor
        self.assertIn(vid, self._ids("qada-77120"))  # sin distinguir mayúsculas
        self.assertIn(vid, self._ids("QADA-771"))  # parcial
        self.assertIn(vid, self._ids("QAIMP-4810", {"partner_id": sup1.id}))  # con su proveedor
        self.assertIn(vid, self._ids("QADA-77120", {"partner_id": sup1.id}))  # con OTRO proveedor también
        self.assertNotIn(vid, self._ids("QA-NO-EXISTE-999"))
        # el alfa y el nombre siguen funcionando igual que en el core
        self.assertEqual(self._ids("QA-ALFA-2")[0], vid)
        self.assertIn(vid, self._ids("Rompecabezas de madera"))

    def test_exact_supplier_code_first(self):
        """Con el proveedor elegido, el código exacto de ese proveedor va antes que
        los artículos cuyo nombre contiene el mismo texto (códigos numéricos cortos)."""
        sup = self.env["res.partner"].create({"name": "QA Proveedor D"})
        other = self.env["product.template"].create({"name": "QA Otro artículo QZX7731", "default_code": "QA-ALFA-3"})
        tmpl = self.env["product.template"].create({
            "name": "QA Perro de peluche", "default_code": "QA-ALFA-4",
            "seller_ids": [(0, 0, {"partner_id": sup.id, "product_code": "QZX7731", "price": 50})],
        })
        with_sup = self._ids("QZX7731", {"partner_id": sup.id})
        self.assertEqual(with_sup[0], tmpl.product_variant_id.id)
        self.assertIn(other.product_variant_id.id, with_sup)
        without = self._ids("QZX7731")
        self.assertEqual(without[0], other.product_variant_id.id)  # el core primero (nombre)
        self.assertIn(tmpl.product_variant_id.id, without)  # y el código de proveedor después
        self.assertEqual(len(without), len(set(without)))  # sin repetidos
