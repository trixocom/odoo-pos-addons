# Part of trx_pos_purchase_receipt. Author: Trixocom. License: LGPL-3.
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestPosPurchaseReceipt(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env["pos.config"].search([("warehouse_id", "!=", False)], limit=1)
        if not cls.config:
            return
        cls.config.write({"trx_receipt_enabled": True, "trx_receipt_blind": False})
        cls.company = cls.config.company_id
        cls.warehouse = cls.config.warehouse_id
        cls.vendor = cls.env["res.partner"].create({"name": "TEST REC Proveedor A", "is_company": True})
        cls.vendor_b = cls.env["res.partner"].create({"name": "TEST REC Proveedor B", "is_company": True})
        cls.product = cls.env["product.product"].create(
            {
                "name": "TEST REC Rompecabezas",
                "type": "consu",
                "is_storable": True,
                "default_code": "TREC-ALFA-1",
                "barcode": "7799999000017",
                "seller_ids": [
                    (0, 0, {"partner_id": cls.vendor.id, "product_code": "PA-0001", "price": 100}),
                    (0, 0, {"partner_id": cls.vendor_b.id, "product_code": "PB-7777", "price": 110}),
                ],
            }
        )
        cls.product2 = cls.env["product.product"].create(
            {
                "name": "TEST REC Memotest",
                "type": "consu",
                "is_storable": True,
                "default_code": "TREC-ALFA-2",
                "seller_ids": [(0, 0, {"partner_id": cls.vendor.id, "product_code": "PA-0002", "price": 50})],
            }
        )
        cls.user = new_test_user(
            cls.env,
            login="trx_rec_cajero",
            groups="point_of_sale.group_pos_user,trx_pos_purchase_receipt.group_pos_receipt",
            company_id=cls.company.id,
            company_ids=[(6, 0, cls.company.ids)],
        )
        cls.user_nogroup = new_test_user(
            cls.env,
            login="trx_rec_sin_permiso",
            groups="point_of_sale.group_pos_user",
            company_id=cls.company.id,
            company_ids=[(6, 0, cls.company.ids)],
        )

    def setUp(self):
        super().setUp()
        if not self.config:
            self.skipTest("Hace falta un punto de venta con depósito")

    def _po(self, lines):
        po = (
            self.env["purchase.order"]
            .with_company(self.company)
            .create(
                {
                    "partner_id": self.vendor.id,
                    "company_id": self.company.id,
                    "partner_ref": "R-0001-00012345",
                    "picking_type_id": self.warehouse.in_type_id.id,
                    "order_line": [(0, 0, {"product_id": p.id, "product_qty": q}) for p, q in lines],
                }
            )
        )
        po.button_confirm()
        picking = po.picking_ids
        self.assertEqual(len(picking), 1)
        return po, picking

    def _api(self, user=None):
        return self.env["stock.picking"].with_user(user or self.user)

    def test_pending_and_load(self):
        po, picking = self._po([(self.product, 5), (self.product2, 2)])
        api = self._api()
        pending = api.trx_pos_receipt_pending(self.config.id)
        row = next(r for r in pending if r["id"] == picking.id)
        self.assertEqual(row["purchase"], po.name)
        self.assertEqual(row["partner_ref"], "R-0001-00012345")
        self.assertEqual(row["demand"], 7)
        self.assertGreaterEqual(api.trx_pos_receipt_count(self.config.id), 1)
        data = api.trx_pos_receipt_load(self.config.id, picking.id)
        line = next(l for l in data["lines"] if l["product_id"] == self.product.id)
        # Código de barras, alfa y código del proveedor de la OC; el del otro proveedor aparte
        self.assertEqual(line["codes"], ["7799999000017", "TREC-ALFA-1", "PA-0001"])
        self.assertEqual(line["vendor_code"], "PA-0001")
        self.assertEqual(line["other_codes"], ["PB-7777"])
        self.assertEqual(line["demand"], 5)
        self.assertEqual(api.trx_pos_receipt_identify(self.config.id, "PB-7777"), self.product.display_name)

    def test_access_denied_without_group(self):
        self._po([(self.product, 1)])
        with self.assertRaises(AccessError):
            self._api(self.user_nogroup).trx_pos_receipt_pending(self.config.id)

    def test_blind_hides_demand(self):
        self.config.trx_receipt_blind = True
        _po, picking = self._po([(self.product, 5)])
        api = self._api()
        data = api.trx_pos_receipt_load(self.config.id, picking.id)
        self.assertTrue(data["blind"])
        self.assertIs(data["lines"][0]["demand"], False)
        row = next(r for r in api.trx_pos_receipt_pending(self.config.id) if r["id"] == picking.id)
        self.assertIs(row["demand"], False)
        # A ciegas lo faltante queda siempre pendiente
        move = picking.move_ids
        res = api.trx_pos_receipt_validate(self.config.id, picking.id, {str(move.id): 3})
        self.assertEqual(picking.state, "done")
        self.assertTrue(res["backorder"])
        self.config.trx_receipt_blind = False

    def test_save_progress(self):
        _po, picking = self._po([(self.product, 5)])
        move = picking.move_ids
        self._api().trx_pos_receipt_save(self.config.id, picking.id, {str(move.id): 2})
        self.assertEqual(move.trx_pos_scanned_qty, 2)
        self.assertEqual(picking.state, "assigned")

    def test_shortage_requires_decision(self):
        _po, picking = self._po([(self.product, 5)])
        with self.assertRaises(UserError):
            self._api().trx_pos_receipt_validate(self.config.id, picking.id, {str(picking.move_ids.id): 3})

    def test_nothing_scanned(self):
        _po, picking = self._po([(self.product, 5)])
        with self.assertRaises(UserError):
            self._api().trx_pos_receipt_validate(self.config.id, picking.id, {str(picking.move_ids.id): 0}, "backorder")

    def test_partial_backorder(self):
        po, picking = self._po([(self.product, 5), (self.product2, 2)])
        m1 = picking.move_ids.filtered(lambda m: m.product_id == self.product)
        m2 = picking.move_ids.filtered(lambda m: m.product_id == self.product2)
        res = self._api().trx_pos_receipt_validate(
            self.config.id, picking.id, {str(m1.id): 3, str(m2.id): 0}, "backorder", "Cajera Test"
        )
        self.assertEqual(picking.state, "done")
        backorder = self.env["stock.picking"].search([("backorder_id", "=", picking.id)])
        self.assertEqual(res["backorder"], backorder.name)
        self.assertEqual(sorted(backorder.move_ids.mapped("product_uom_qty")), [2, 2])
        self.assertEqual(po.order_line.filtered(lambda l: l.product_id == self.product).qty_received, 3)
        self.assertIn("Cajera Test", picking.message_ids[0].body)
        # El saldo aparece como pendiente en el POS
        pending_ids = [r["id"] for r in self._api().trx_pos_receipt_pending(self.config.id)]
        self.assertIn(backorder.id, pending_ids)
        self.assertNotIn(picking.id, pending_ids)

    def test_partial_no_backorder(self):
        po, picking = self._po([(self.product, 5)])
        res = self._api().trx_pos_receipt_validate(
            self.config.id, picking.id, {str(picking.move_ids.id): 4}, "cancel"
        )
        self.assertFalse(res["backorder"])
        self.assertFalse(self.env["stock.picking"].search([("backorder_id", "=", picking.id)]))
        self.assertEqual(po.order_line.qty_received, 4)

    def _set_block_over(self, value):
        ptype = self.warehouse.in_type_id
        if "block_additional_quantity" not in ptype._fields:
            if value:
                self.skipTest("stock_ux no instalado")
            return
        ptype.block_additional_quantity = value

    def test_over_receipt_blocked(self):
        self._set_block_over(True)
        _po, picking = self._po([(self.product, 5)])
        data = self._api().trx_pos_receipt_load(self.config.id, picking.id)
        self.assertTrue(data["block_over"])
        with self.assertRaises(UserError):
            self._api().trx_pos_receipt_validate(self.config.id, picking.id, {str(picking.move_ids.id): 7})

    def test_over_receipt(self):
        self._set_block_over(False)
        po, picking = self._po([(self.product, 5)])
        res = self._api().trx_pos_receipt_validate(self.config.id, picking.id, {str(picking.move_ids.id): 7})
        self.assertTrue(res["over"])
        self.assertEqual(po.order_line.qty_received, 7)

    def test_other_warehouse_not_visible(self):
        other_wh = self.env["stock.warehouse"].search(
            [("company_id", "=", self.company.id), ("id", "!=", self.warehouse.id)], limit=1
        )
        if not other_wh:
            self.skipTest("Hace falta otro depósito en la compañía")
        po = (
            self.env["purchase.order"]
            .with_company(self.company)
            .create(
                {
                    "partner_id": self.vendor.id,
                    "company_id": self.company.id,
                    "picking_type_id": other_wh.in_type_id.id,
                    "order_line": [(0, 0, {"product_id": self.product.id, "product_qty": 1})],
                }
            )
        )
        po.button_confirm()
        ids = [r["id"] for r in self._api().trx_pos_receipt_pending(self.config.id)]
        self.assertNotIn(po.picking_ids.id, ids)
        with self.assertRaises(UserError):
            self._api().trx_pos_receipt_load(self.config.id, po.picking_ids.id)
