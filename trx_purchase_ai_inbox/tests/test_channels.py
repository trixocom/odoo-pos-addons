# Part of trx_purchase_ai_inbox. Author: Trixocom. License: LGPL-3.
from collections import namedtuple
from unittest.mock import patch

from odoo.tests import tagged

from .test_inbox import TestPurchaseAiInbox

Attachment = namedtuple("Attachment", ("fname", "content", "info"))
PDF = b"%PDF-1.4\n" + b"0" * 2000


@tagged("post_install", "-at_install")
class TestInboxChannels(TestPurchaseAiInbox):
    def _mail(self, attachments, subject="Factura 38359", email_from="facturacion@proveedor.com"):
        return {"subject": subject, "email_from": email_from, "attachments": attachments,
                "message_id": "<qa@test>", "body": "<p>adjunto factura</p>"}

    def test_email_creates_one_record_per_document(self):
        Inbox = self.env["trx.purchase.inbox"]
        server = self.env["fetchmail.server"].create({"name": "QA compras", "server": "imap.example.com", "server_type": "imap",
                                                      "user": "compras@example.com", "password": "x"})
        server.trx_ai_inbox = True
        self.assertEqual(server.object_id.model, "trx.purchase.inbox")
        msg = self._mail([
            Attachment("FACA0000600038359.pdf", PDF, {}),
            Attachment("logo.png", b"\x89PNG" + b"0" * 500, {"cid": "logo"}),       # firma: se ignora
            Attachment("pedido.docx", b"PK" + b"0" * 3000, {}),
            Attachment("leeme.txt", b"hola", {}),                                    # no es comprobante
        ])
        first = Inbox.with_context(default_fetchmail_server_id=server.id).message_new(msg)
        recs = Inbox.search([("source_subject", "=", "Factura 38359")])
        self.assertEqual(len(recs), 2)
        self.assertIn(first, recs)
        self.assertEqual(set(recs.mapped("file_name")), {"FACA0000600038359.pdf", "pedido.docx"})
        self.assertEqual(set(recs.mapped("source")), {"email"})
        self.assertEqual(recs.mapped("source_ref")[0], "facturacion@proveedor.com")
        self.assertEqual(recs.fetchmail_server_id, server)
        self.assertTrue(all(r.state == "draft" and r.name.startswith("FP/") for r in recs))
        server.trx_ai_inbox = False
        self.assertFalse(server.object_id)

    def test_email_without_document_is_rejected(self):
        rec = self.env["trx.purchase.inbox"].message_new(self._mail([], subject="Consulta"))
        self.assertEqual(rec.state, "rejected")
        self.assertIn("no trae un comprobante", rec.reject_reason)

    def test_batch_scan_same_result_as_manual(self):
        """Lo que llega por correo se lee en lote y queda igual que la carga manual (para evaluación)."""
        Inbox = self.env["trx.purchase.inbox"]
        rec = Inbox.message_new(self._mail([Attachment("factura.pdf", PDF, {})]))
        client = type(self.env["trx.purchase.ai.client"])
        with patch.object(client, "extract_invoice", return_value=(self.data, {"model": "test"})):
            Inbox.with_context(trx_no_commit=True)._cron_scan_pending()
        self.assertEqual(rec.state, "review")            # hay un artículo nuevo: queda para revisar
        self.assertEqual(rec.partner_id, self.partner)
        self.assertEqual(len(rec.line_ids), 3)
        self.assertFalse(rec.scan_error)
        # el mismo comprobante subido a mano: duplicado
        manual = Inbox.create({"company_id": self.company.id, "file_name": "qa.pdf"})
        manual._apply_result(self.data, {})
        self.assertEqual(manual.state, "rejected")
        self.assertEqual(manual.duplicate_of_id, rec)

    def test_batch_scan_error_is_kept(self):
        Inbox = self.env["trx.purchase.inbox"]
        rec = Inbox.message_new(self._mail([Attachment("factura.pdf", PDF, {})]))
        client = type(self.env["trx.purchase.ai.client"])
        with patch.object(client, "extract_invoice", side_effect=ValueError("sin conexión")):
            Inbox.with_context(trx_no_commit=True)._cron_scan_pending()
        self.assertEqual(rec.state, "draft")
        self.assertEqual(rec.scan_attempts, 1)
        self.assertIn("sin conexión", rec.scan_error)
        with patch.object(client, "extract_invoice", return_value=(self.data, {"model": "test"})):
            rec.action_scan_selected()
        self.assertEqual(rec.state, "review")
        self.assertFalse(rec.scan_error)

    def test_auto_scan_off(self):
        self.env["ir.config_parameter"].sudo().set_param("trx_purchase_ai_inbox.auto_scan", "0")
        rec = self.env["trx.purchase.inbox"].message_new(self._mail([Attachment("factura.pdf", PDF, {})]))
        client = type(self.env["trx.purchase.ai.client"])
        with patch.object(client, "extract_invoice", return_value=(self.data, {"model": "test"})) as m:
            self.env["trx.purchase.inbox"].with_context(trx_no_commit=True)._cron_scan_pending()
            m.assert_not_called()
        self.assertEqual(rec.state, "draft")


# Los tests heredados de TestPurchaseAiInbox ya corren en su clase: acá sólo se reutiliza el setUp.
for _name in dir(TestPurchaseAiInbox):
    if _name.startswith("test_") and _name not in TestInboxChannels.__dict__:
        setattr(TestInboxChannels, _name, None)
