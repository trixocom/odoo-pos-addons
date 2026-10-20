# Part of trx_purchase_ai_inbox. Author: Trixocom. License: LGPL-3.
"""Pruebas sin API: se simula el resultado de la lectura y se verifica el prorrateo del descuento
global, el reconocimiento por EAN / código de proveedor, el control de totales y la OC."""
import base64
import io
import zipfile

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
        self.assertTrue(l3.product_id.available_in_pos and l3.product_id.sale_ok and l3.product_id.active)
        self.assertEqual(l3.product_id.default_code, "QAT1")
        self.assertEqual(l3.product_id.barcode, "7799990000017")
        self.assertEqual(l3.product_id.list_price, 18.0)  # 9 × 2
        self.assertTrue(l3.product_id.categ_id)
        incoming = self.env["stock.picking.type"].search([("code", "=", "incoming"), ("company_id", "=", self.company.id)], order="id desc", limit=1)
        inbox.picking_type_id = incoming
        inbox.action_create_po()
        po = inbox.purchase_id
        self.assertEqual(po.state, "purchase")
        self.assertEqual(po.picking_type_id, incoming)
        self.assertEqual(po.picking_ids.picking_type_id, incoming)
        self.assertEqual(inbox.state, "done")
        self.assertEqual(po.partner_ref, "FACTURA A 00006-00038359")
        self.assertAlmostEqual(po.amount_untaxed, 252.0, places=2)
        self.assertAlmostEqual(po.amount_total, 304.92, places=2, msg=str([(l.tax_ids.ids, l.tax_ids.mapped("price_include_override"), l.price_tax, l.price_unit, l.product_qty) for l in po.order_line]) + " cia=%s ctx=%s cia_inc=%s" % (self.env.company.id, self.env.context, self.company.account_price_include))
        self.assertTrue(po.picking_ids)
        seller = self.p1.seller_ids.filtered(lambda s: s.partner_id == self.partner)
        self.assertAlmostEqual(seller.price, 90.0, places=4)
        rows = self.env["trx.product.price.history"].search([("product_tmpl_id", "=", self.p1.id), ("origin", "=", "invoice")])
        self.assertTrue(rows)

    def test_publish_activates_archived_product(self):
        """Un artículo reconocido pero archivado / no disponible en POS se activa al publicar."""
        self.p2.write({"available_in_pos": False})
        self.p2.action_archive()
        data = dict(self.data)
        data["lineas"] = [dict(self.data["lineas"][1])]
        data["descuentos_globales"] = []
        data["totales"] = {"neto_gravado": 50.0, "iva": 10.5, "total": 60.5}
        self.inbox._apply_result(data, {})
        line = self.inbox.line_ids
        if not line.product_id:  # los archivados no se reconocen solos: se elige a mano
            line.write({"product_id": self.p2.with_context(active_test=False).product_variant_ids[:1].id, "match_state": "matched", "match_by": "manual"})
        self.inbox.action_publish_pos()
        self.assertTrue(self.p2.active)
        self.assertTrue(self.p2.available_in_pos)

    def test_name_match_respects_ean(self):
        """Mismo nombre pero otro EAN impreso: es otro artículo, no se asocia."""
        data = dict(self.data)
        data["lineas"] = [{"codigo_proveedor": "ZZ999", "ean": "7799990000024", "descripcion": "QA Puzzle 3D", "cantidad": 1,
                           "precio_unitario": 10.0, "importe_linea": 10.0, "alicuota_iva": 21},
                          {"codigo_proveedor": "ZZ998", "ean": "", "descripcion": "QA Puzzle 3D", "cantidad": 1,
                           "precio_unitario": 10.0, "importe_linea": 10.0, "alicuota_iva": 21}]
        data["descuentos_globales"] = []
        data["totales"] = {"neto_gravado": 20.0, "iva": 4.2, "total": 24.2}
        self.inbox._apply_result(data, {})
        l1, l2 = self.inbox.line_ids.sorted("sequence")
        self.assertEqual(l1.match_state, "new")          # EAN distinto al del artículo con ese nombre
        self.assertEqual(l2.match_state, "suggested")    # sin EAN: el nombre es sólo una sugerencia
        self.assertEqual(l2.product_id.product_tmpl_id, self.p1)

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

    def test_docx_blocks(self):
        """Word (.docx): párrafos y tablas → bloque de texto para la IA; .doc → error claro."""
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xml = ('<w:document xmlns:w="%s"><w:body><w:p><w:r><w:t>FACTURA A 0001-00000123</w:t></w:r></w:p>'
               '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>DFZ07837</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>AGUA WOW /24</w:t></w:r></w:p></w:tc>'
               '<w:tc><w:p><w:r><w:t>6199.00</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>') % ns
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", xml)
        client = self.env["trx.purchase.ai.client"]
        blocks = client._document_blocks(base64.b64encode(buf.getvalue()).decode(), "", "pedido.docx")
        self.assertEqual(blocks[0]["type"], "text")
        self.assertIn("FACTURA A 0001-00000123", blocks[0]["text"])
        self.assertIn("DFZ07837 | AGUA WOW /24 | 6199.00", blocks[0]["text"])
        with self.assertRaises(Exception):
            client._document_blocks("", "application/msword", "viejo.doc")
        self.assertEqual(client._document_blocks("eA==", "application/pdf", "f.pdf")[0]["type"], "document")

    def test_non_fiscal_quote(self):
        """Presupuesto / factura no fiscal: OC y factura sin IVA, factura en el diario NF sin documentos (se crea si no existe)."""
        data = dict(self.data)
        data["comprobante"] = {"tipo": "SOLICITUD DE PEDIDO/PRESUPUESTO", "letra": "", "numero": "0000200005695", "fecha": "2026-10-10"}
        data["lineas"] = [dict(self.data["lineas"][0]), dict(self.data["lineas"][1])]
        data["descuentos_globales"] = [{"descripcion": "DTO.%", "porcentaje": 10, "importe": 0}]
        data["totales"] = {"neto_gravado": 225.0, "iva": 0.0, "total": 225.0}   # (200 + 50) − 10 %, sin IVA
        self.inbox._apply_result(data, {})
        self.assertTrue(self.inbox.non_fiscal)
        self.assertNotEqual(self.inbox.state, "rejected")
        self.assertAlmostEqual(self.inbox.amount_tax_calc, 0.0, places=2)
        self.assertTrue(self.inbox.totals_ok)
        self.assertAlmostEqual(self.inbox.line_ids.sorted("sequence")[0].price_net_untaxed, 90.0, places=4)
        self.inbox.action_create_po()
        po = self.inbox.purchase_id
        self.assertEqual(po.state, "purchase")
        self.assertFalse(po.order_line.tax_ids)
        self.assertAlmostEqual(po.amount_total, 225.0, places=2)
        self.assertTrue(po.partner_ref.startswith("NF "))
        self.inbox.action_create_bill()
        move = self.inbox.invoice_id
        self.assertEqual(move.journal_id.type, "purchase")
        self.assertFalse(move.journal_id.l10n_latam_use_documents)
        self.assertFalse(move.l10n_latam_document_type_id)
        self.assertAlmostEqual(move.amount_tax, 0.0, places=2)
        self.assertAlmostEqual(move.amount_total, 225.0, places=2)
        self.assertEqual(move.invoice_line_ids.mapped("purchase_line_id"), po.order_line)
        # el diario NF se reutiliza
        self.assertEqual(self.env["trx.purchase.inbox"]._get_nf_purchase_journal(self.company), move.journal_id)

    def test_non_fiscal_with_printed_vat(self):
        """No fiscal que suma IVA aparte: sin crédito fiscal, el IVA va al costo."""
        data = dict(self.data)
        data["comprobante"] = {"tipo": "PRESUPUESTO", "letra": "", "numero": "77"}
        data["lineas"] = [dict(self.data["lineas"][1])]
        data["descuentos_globales"] = []
        data["totales"] = {"neto_gravado": 50.0, "iva": 10.5, "total": 60.5}
        self.inbox._apply_result(data, {})
        self.assertTrue(self.inbox.non_fiscal)
        self.assertAlmostEqual(self.inbox.line_ids.price_net_untaxed, 60.5, places=4)
        self.assertTrue(self.inbox.totals_ok)

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
