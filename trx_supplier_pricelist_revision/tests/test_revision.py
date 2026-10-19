# Part of trx_supplier_pricelist_revision. Author: Trixocom. License: LGPL-3.
import base64
import io
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

from .. import file_parser


def _xlsx(rows):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hoja1"
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@tagged("post_install", "-at_install")
class TestSupplierPricelistRevision(TransactionCase):
    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({
            "name": "QA Derajim", "supplier_rank": 1, "trx_alfa_prefix": "QAD", "trx_alfa_next": 1,
            "trx_pricelist_discount": 10.0, "trx_pvp_rule": "list_factor", "trx_pvp_factor": 2.1, "trx_pvp_rounding": "1",
        })
        # artículo existente con código de proveedor 41241, lista 12790 y 10 % (campo discount del core), PVP 26859
        self.p_up = self.env["product.template"].create({
            "name": "QA 12-Pc Dinos", "type": "consu", "default_code": "QAD-OLD1", "list_price": 26859.0,
            "seller_ids": [(0, 0, {"partner_id": self.partner.id, "product_code": "41241", "price": 12790.0, "discount": 10.0})],
        })
        # artículo existente reconocido por código de barras, cuyo precio baja
        self.p_down = self.env["product.template"].create({
            "name": "QA Tambor", "type": "consu", "default_code": "QAD-OLD2", "list_price": 40000.0,
            "barcode": "7790000000999",
            "seller_ids": [(0, 0, {"partner_id": self.partner.id, "product_code": "817", "price": 20000.0, "discount": 10.0})],
        })
        self.rows = [
            ["codigo_pro", "detalle", "precio", "bon1", "bon2", "COD_ALFABA", "sugerido", "unidades"],
            [41241, "12-Pc Dinos", 14069, 10, 0, "732396412418", 29545, 1],
            [817, "Super Tambor", 15500, 10, 0, 7790000000999, 31000, 1],
            ["WLH-802", "24 Piezas Goma Eva Bloques Magnéticos", 29000, 10, 0, "SC", 58000, 1],
            [20180, "Tablero para Atornillar", 18000, 10, 0, "6927049021800", 37800, 1],
            [None, None, None, 10, 0, None, None, 1],
        ]
        self.Revision = self.env["trx.supplier.pricelist.revision"]
        self.History = self.env["trx.product.price.history"]

    def _revision(self, rows=None):
        rev = self.Revision.create({
            "partner_id": self.partner.id,
            "file": base64.b64encode(_xlsx(rows or self.rows)),
            "file_name": "DERAJIM QA.xlsx",
        })
        rev.action_load_file()
        return rev

    def test_parser_recognizes_anita_format(self):
        parsed = file_parser.parse(_xlsx(self.rows), "lista.xlsx")
        self.assertTrue(parsed)
        sheet, header_map, data = parsed
        self.assertEqual(sheet, "Hoja1")
        self.assertEqual({"code", "name", "list_price", "discount", "barcode", "suggested"}, set(header_map))
        self.assertEqual(len(data), 4)
        self.assertEqual(data[0]["code"], "41241")
        self.assertEqual(data[1]["barcode"], "7790000000999")
        self.assertEqual(data[2]["barcode"], "")  # SC = sin código
        self.assertEqual(data[0]["discount"], 10.0)

    def test_load_match_and_proposals(self):
        rev = self._revision()
        self.assertTrue(rev.name.startswith("LP/"))
        self.assertEqual(rev.state, "review")
        self.assertEqual(rev.discount_pct, 10.0)
        self.assertEqual(rev.pvp_factor, 2.1)
        self.assertEqual(len(rev.line_ids), 4)
        up = rev.line_ids.filtered(lambda l: l.supplier_code == "41241")
        down = rev.line_ids.filtered(lambda l: l.supplier_code == "817")
        new = rev.line_ids.filtered(lambda l: l.supplier_code == "WLH-802")
        self.assertEqual(up.product_tmpl_id, self.p_up)
        self.assertEqual(up.match_by, "supplier_code")
        self.assertAlmostEqual(up.cost_current, 12790.0 * 0.9, places=2)
        self.assertAlmostEqual(up.net_cost, 14069.0 * 0.9, places=2)
        self.assertEqual(up.trend, "up")
        self.assertAlmostEqual(up.cost_var_pct, 0.1, places=3)
        self.assertEqual(up.pvp_current, 26859.0)
        self.assertEqual(up.pvp_proposed, 29545.0)  # 14069 × 2.1 = 29544.9 → redondeo a la unidad
        self.assertEqual(up.decision, "apply")
        self.assertEqual(down.product_tmpl_id, self.p_down)
        self.assertEqual(down.match_by, "barcode")
        self.assertEqual(down.trend, "down")
        self.assertEqual(down.decision, "keep_pvp")
        self.assertEqual(down.pvp_proposed, 40000.0)
        self.assertEqual(new.match_state, "new")
        self.assertEqual(new.decision, "skip")
        self.assertEqual(rev.count_up, 1)
        self.assertEqual(rev.count_down, 1)
        self.assertEqual(rev.count_new, 2)

    def test_apply_now_updates_supplier_price_pvp_and_history(self):
        rev = self._revision()
        rev.action_apply_now()
        self.assertEqual(rev.state, "applied")
        seller = self.p_up.seller_ids.filtered(lambda s: s.partner_id == self.partner)
        self.assertEqual(len(seller), 1)
        self.assertEqual(seller.price, 14069.0)
        self.assertEqual(seller.discount, 0.0)
        self.assertTrue(seller.replenishment_cost_rule_id)
        self.assertAlmostEqual(seller.net_price, 14069.0 * 0.9, places=2)
        self.assertEqual(self.p_up.list_price, 29545.0)
        self.assertEqual(self.p_up.replenishment_cost_type, "supplier_price")
        # bajó: costo actualizado, PVP mantenido
        self.assertEqual(self.p_down.list_price, 40000.0)
        seller_down = self.p_down.seller_ids.filtered(lambda s: s.partner_id == self.partner)
        self.assertEqual(seller_down.price, 15500.0)
        rows = self.History.search([("origin_ref", "=", rev.name)])
        self.assertTrue(rows.filtered(lambda r: r.price_type == "list_price" and r.product_tmpl_id == self.p_up and r.new_value == 29545.0))
        self.assertTrue(rows.filtered(lambda r: r.price_type == "supplier_price" and r.product_tmpl_id == self.p_up and r.new_value == 14069.0))
        self.assertTrue(all(r.origin == "revision" for r in rows))
        states = rev.line_ids.mapped("state")
        self.assertEqual(states.count("applied"), 2)
        self.assertEqual(states.count("skipped"), 2)

    def test_schedule_and_cron(self):
        rev = self._revision()
        rev.apply_at = fields.Datetime.now() - timedelta(minutes=1)
        rev.action_schedule()
        self.assertEqual(rev.state, "scheduled")
        self.Revision._cron_apply_scheduled()
        self.assertEqual(rev.state, "applied")
        self.assertEqual(self.p_up.list_price, 29545.0)
        rev2 = self._revision()
        rev2.apply_at = fields.Datetime.now() + timedelta(days=1)
        rev2.action_schedule()
        self.Revision._cron_apply_scheduled()
        self.assertEqual(rev2.state, "scheduled")  # todavía no vence

    def test_create_product_with_alfa_sequence(self):
        rev = self._revision()
        new_lines = rev.line_ids.filtered(lambda l: l.match_state == "new").sorted("sequence")
        self.assertEqual(len(new_lines), 2)
        new_lines.action_create_product()
        codes = new_lines.mapped("product_tmpl_id.default_code")
        self.assertEqual(codes, ["QAD1", "QAD2"])
        self.assertNotIn("-", codes[0])
        self.assertEqual(self.partner.trx_alfa_next, 3)
        tmpl = new_lines[0].product_tmpl_id
        self.assertEqual(tmpl.name, "24 Piezas Goma Eva Bloques Magnéticos")
        self.assertFalse(tmpl.barcode)  # SC
        self.assertEqual(tmpl.list_price, 60900.0)  # 29000 × 2.1
        seller = tmpl.seller_ids
        self.assertEqual(seller.partner_id, self.partner)
        self.assertEqual(seller.product_code, "WLH-802")
        self.assertAlmostEqual(seller.net_price, 29000.0 * 0.9, places=2)
        self.assertEqual(new_lines[1].product_tmpl_id.barcode, "6927049021800")
        self.assertTrue(all(l.match_state == "matched" and l.decision == "apply" for l in new_lines))
        # el prefijo por defecto sale de las 3 primeras letras del nombre
        other = self.env["res.partner"].create({"name": "Baby Club SA", "supplier_rank": 1})
        self.assertEqual(other._trx_next_alfa(), "BAB1")
