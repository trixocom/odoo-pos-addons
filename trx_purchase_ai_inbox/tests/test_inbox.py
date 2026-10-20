# Part of trx_purchase_ai_inbox. Author: Trixocom. License: LGPL-3.
"""Pruebas sin API: se simula el resultado de la lectura y se verifica el prorrateo del descuento
global, el reconocimiento por EAN / código de proveedor, el control de totales y la OC."""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPurchaseAiInbox(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.partner = self.env["res.partner"].create({
            "name": "QA Tapimovil SA", "is_company": True, "vat": "30111111118", "supplier_rank": 1,
            "trx_alfa_prefix": "QAT", "trx_alfa_next": 1, "trx_pvp_rule": "cost_factor", "trx_pvp_factor": 2.0, "trx_pvp_rounding": "1",
        })
        self.p1 = self.env["product.template"].create({
            "name": "QA Puzzle 3D", "type": "consu", "default_code": "QAT-OLD1", "barcode": "7794008179815",
            "seller_ids": [(0, 0, {"partner_id": self.partner.id, "product_code": "DFZ17981", "price": 80.0})],
        })
        self.p2 = self.env["product.template"].create({
            "name": "QA Microfono", "type": "consu", "default_code": "QAT-OLD2",
            "seller_ids": [(0, 0, {"partner_id": self.partner.id, "product_code": "78072", "price": 50.0})],
        })
        self.data = {
            "proveedor": {"razon_social": "QA TAPIMOVIL SA", "cuit": "30-11111111-8"},
            "receptor": {"razon_social": self.company.name, "cuit": self.company.vat or ""},
            "comprobante": {"tipo": "FACTURA", "letra": "A", "punto_venta": "6", "numero": "38359", "fecha": "2026-10-10", "cae": "76400000000001"},
            "lineas": [
                {"codigo_proveedor": "DFZ17981", "ean": "7794008179815", "descripcion": "PUZZLE 3D LENTICULAR", "cantidad": 2, "precio_unitario": 100.0, "descuento_linea_pct": 0, "importe_linea": 200.0, "alicuota_iva": 21},
                {"codigo_proveedor": "78072", "ean": "", "descripcion": "MICROFONO KARAOKE", "cantidad": 1, "precio_unitario": 50.0, "descuento_linea_pct": 0, "importe_linea": 50.0, "alicuota_iva": 21},
                {"codigo_proveedor": "NEW1", "ean": "7799990000017", "descripcion": "QA ARTICULO NUEVO ZZ", "cantidad": 3, "precio_unitario": 10.0, "descuento_linea_pct": 0, "importe_linea": 30.0, "alicuota_iva": 21},
            ],
            "descuentos_globales": [{"descripcion": "Bonificación", "porcentaje": 10, "importe": 0}],
            "otros_cargos": [],
            "percepciones": [],
            # líneas 280 − 10 % = 252 neto; IVA 21 % = 52.92; total 304.92
            "totales": {"neto_gravado": 252.0, "iva": 52.92, "total": 304.92},
            "observaciones": "",
        }
        self.inbox = self.env["trx.purchase.inbox"].create({"company_id": self.company.id, "file_name": "qa.pdf"})

    def test_global_discount_matching_and_po(self):
        inbox = self.inbox
        inbox._apply_result(self.data, {"model": "test"})
        self.assertEqual(inbox.partner_id, self.partner)
        self.assertEqual(inbox.doc_number, "00006-00038359")
        self.assertAlmostEqual(inbox.global_discount_pct, 10.0, places=4)
        l1, l2, l3 = inbox.line_ids.sorted("sequence")
        self.assertEqual(l1.match_by, "ean")
        self.assertEqual(l1.product_id.product_tmpl_id, self.p1)
        self.assertAlmostEqual(l1.price_net_untaxed, 90.0, places=4)   # 100 − 10 % global
        self.assertAlmostEqual(l1.cost_current, 80.0, places=4)
        self.assertTrue(l1.price_up)
        self.assertEqual(l2.match_by, "supplier_code")
        self.assertAlmostEqual(l2.price_net_untaxed, 45.0, places=4)
        self.assertFalse(l2.price_up)
        self.assertEqual(l3.match_state, "new")
        self.assertTrue(l3.ean_valid)
        self.assertTrue(inbox.totals_ok)
        self.assertAlmostEqual(inbox.amount_total_calc, 304.92, places=2)
        self.assertEqual(inbox.state, "review")  # hay una línea nueva
        with self.assertRaises(Exception):
            inbox.action_create_po()
        inbox.action_create_products()
        self.assertEqual(l3.product_id.default_code, "QAT1")
        self.assertEqual(l3.product_id.barcode, "7799990000017")
        self.assertEqual(l3.product_id.list_price, 18.0)  # 9 × 2
        self.assertTrue(l3.product_id.categ_id)
        inbox.action_create_po()
        po = inbox.purchase_id
        self.assertEqual(po.state, "purchase")
        self.assertEqual(inbox.state, "done")
        self.assertEqual(po.partner_ref, "FACTURA A 00006-00038359")
        self.assertAlmostEqual(po.amount_untaxed, 252.0, places=2)
        self.assertAlmostEqual(po.amount_total, 304.92, places=2, msg=str([(l.tax_ids.ids, l.tax_ids.mapped("price_include_override"), l.price_tax, l.price_unit, l.product_qty) for l in po.order_line]) + " cia=%s ctx=%s cia_inc=%s" % (self.env.company.id, self.env.context, self.company.account_price_include))
        self.assertTrue(po.picking_ids)
        seller = self.p1.seller_ids.filtered(lambda s: s.partner_id == self.partner)
        self.assertAlmostEqual(seller.price, 90.0, places=4)
        rows = self.env["trx.product.price.history"].search([("product_tmpl_id", "=", self.p1.id), ("origin", "=", "invoice")])
        self.assertTrue(rows)

    def test_reject_own_company_and_remito(self):
        data = dict(self.data)
        data["proveedor"] = {"razon_social": self.company.name, "cuit": self.company.vat or "30707816798"}
        if not self.company.vat:
            self.company.vat = "30707816798"
        self.inbox._apply_result(data, {})
        self.assertEqual(self.inbox.state, "rejected")
        self.assertIn("no es una factura de compra", self.inbox.reject_reason)
        self.inbox.action_reset()
        data = dict(self.data)
        data["comprobante"] = dict(self.data["comprobante"], tipo="REMITO")
        self.inbox._apply_result(data, {})
        self.assertEqual(self.inbox.state, "rejected")

    def test_perceptions_to_vendor_bill(self):
        """Percepción IIBB impresa → impuesto de compra de l10n_ar (activado si estaba archivado) en la factura de proveedor."""
        Tax = self.env["account.tax"].with_context(active_test=False)
        group = self.env["account.tax.group"].search([("company_id", "=", self.company.id), ("name", "=ilike", "Perc IIBB P. Buenos Aires")], limit=1)
        self.assertTrue(group, "plan de impuestos l10n_ar")
        pba = Tax.search([("company_id", "=", self.company.id), ("type_tax_use", "=", "purchase"), ("tax_group_id", "=", group.id)], limit=1)
        pba.active = False  # simulamos que está archivado
        data = dict(self.data)
        data["lineas"] = [dict(self.data["lineas"][0]), dict(self.data["lineas"][1])]
        data["percepciones"] = [
            {"descripcion": "Perc. Ing. Brutos Bs. As. 2%", "tipo": "iibb", "jurisdiccion": "Buenos Aires", "alicuota": 2, "base": 225.0, "importe": 4.50},
            {"descripcion": "Percepción IVA RG 2408", "tipo": "iva", "importe": 6.75},
        ]
        # líneas 250 − 10 % = 225 neto; IVA 47.25; percepciones 11.25; total 283.50
        data["totales"] = {"neto_gravado": 225.0, "iva": 47.25, "percepciones": 11.25, "total": 283.50}
        self.inbox._apply_result(data, {})
        self.assertEqual(len(self.inbox.perception_ids), 2)
        p_iibb, p_iva = self.inbox.perception_ids.sorted("sequence")
        self.assertEqual(p_iibb.kind, "iibb")
        self.assertEqual(p_iibb.jurisdiction, "P. Buenos Aires")
        self.assertEqual(p_iibb.tax_id, pba)
        self.assertTrue(pba.active)
        self.assertEqual(p_iibb.tax_state, "activated")
        self.assertEqual(p_iva.kind, "iva")
        self.assertEqual(p_iva.tax_id.tax_group_id.l10n_ar_tribute_afip_code, "06")
        self.assertEqual(p_iva.tax_state, "found")
        self.assertAlmostEqual(self.inbox.amount_perceptions, 11.25, places=2)
        self.assertTrue(self.inbox.totals_ok)
        self.inbox.action_create_po()
        self.assertEqual(self.inbox.purchase_id.state, "purchase")
        self.assertAlmostEqual(self.inbox.purchase_id.amount_total, 272.25, places=2)  # la OC no lleva percepciones
        self.inbox.action_create_bill()
        move = self.inbox.invoice_id
        self.assertEqual(move.state, "draft")
        self.assertEqual(move.move_type, "in_invoice")
        self.assertEqual(move.l10n_latam_document_number, "00006-00038359")
        self.assertEqual(move.l10n_latam_document_type_id.code, "1")
        self.assertEqual(move.invoice_line_ids.mapped("purchase_line_id"), self.inbox.purchase_id.order_line)
        self.assertAlmostEqual(move.amount_untaxed, 225.0, places=2)
        iibb_lines = move.line_ids.filtered(lambda l: l.tax_line_id == pba)
        self.assertAlmostEqual(sum(iibb_lines.mapped("amount_currency")), 4.50, places=2)
        iva_perc_lines = move.line_ids.filtered(lambda l: l.tax_line_id == p_iva.tax_id)
        self.assertAlmostEqual(sum(iva_perc_lines.mapped("amount_currency")), 6.75, places=2)
        self.assertAlmostEqual(move.amount_total, 283.50, places=2)
        self.assertEqual(self.inbox.purchase_id.invoice_ids, move)

    def test_perception_iibb_without_province(self):
        """'ING.BRUTOS 4%' sin provincia → jurisdicción del domicilio de la compañía (CABA), marcada como supuesta."""
        caba = self.env["res.country.state"].search([("country_id.code", "=", "AR"), ("code", "=", "C")], limit=1)
        self.assertTrue(caba)
        self.company.partner_id.state_id = caba
        data = dict(self.data)
        data["lineas"] = [dict(self.data["lineas"][1])]
        data["descuentos_globales"] = []
        data["percepciones"] = [{"descripcion": "Percepciones Realizadas sobre la factura 902 ING.BRUTOS 4.00", "tipo": "iibb", "alicuota": 4, "importe": 2.0}]
        data["totales"] = {"neto_gravado": 50.0, "iva": 10.5, "percepciones": 2.0, "total": 62.5}
        self.inbox._apply_result(data, {})
        perc = self.inbox.perception_ids
        self.assertEqual(perc.kind, "iibb")
        self.assertEqual(perc.jurisdiction, "CABA")
        self.assertTrue(perc.jurisdiction_guessed)
        self.assertTrue(perc.tax_id)
        self.assertEqual(perc.tax_id.tax_group_id.l10n_ar_tribute_afip_code, "07")
        self.assertIn("CABA", perc.tax_id.tax_group_id.with_context(lang="en_US").name)

    def test_prices_with_tax_included(self):
        data = dict(self.data)
        data["comprobante"] = dict(self.data["comprobante"], letra="B")
        data["lineas"] = [dict(self.data["lineas"][1], precio_unitario=121.0, importe_linea=121.0)]
        data["descuentos_globales"] = []
        data["totales"] = {"neto_gravado": 100.0, "iva": 21.0, "total": 121.0}
        self.inbox._apply_result(data, {})
        line = self.inbox.line_ids
        self.assertTrue(self.inbox.prices_include_tax)
        self.assertAlmostEqual(line.price_net_untaxed, 100.0, places=4)
        self.assertTrue(self.inbox.totals_ok)
