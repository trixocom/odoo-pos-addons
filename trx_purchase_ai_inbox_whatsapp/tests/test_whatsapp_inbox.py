# Part of trx_purchase_ai_inbox_whatsapp. Author: Trixocom. License: LGPL-3.
from odoo.tests import TransactionCase, tagged

PDF = b"%PDF-1.4\n" + b"0" * 2000


@tagged("post_install", "-at_install")
class TestWhatsappInbox(TransactionCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["whatsapp.account"].create({"name": "QA compras"})

    def _event(self, **kw):
        ev = {"from": "5491155550000", "sender_name": "Proveedor QA", "msg_uid": "qa-1", "body": "te paso la factura",
              "attachment": ("factura 123.pdf", PDF, "application/pdf")}
        ev.update(kw)
        return ev

    def test_capture_only_when_enabled(self):
        Inbox = self.env["trx.purchase.inbox"]
        self.assertFalse(self.account.trx_ai_inbox)
        self.account.trx_ai_inbox = True
        recs = self.account._trx_ai_inbox_capture(self._event())
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs.source, "whatsapp")
        self.assertEqual(recs.wa_account_id, self.account)
        self.assertEqual(recs.file_name, "factura 123.pdf")
        self.assertIn("5491155550000", recs.source_ref)
        self.assertEqual(recs.state, "draft")
        self.assertEqual(self.account.trx_ai_inbox_count, 1)
        # foto sin nombre: se nombra por el tipo
        photo = self.account._trx_ai_inbox_capture(self._event(msg_uid="qa-2", attachment=(None, b"\xff\xd8" + b"0" * 900, "image/jpeg")))
        self.assertTrue(photo.file_name.endswith(".jpg"))
        # nota de voz, mensaje propio y audio: no entran
        self.assertFalse(self.account._trx_ai_inbox_capture(self._event(voice=True)))
        self.assertFalse(self.account._trx_ai_inbox_capture(self._event(is_from_me=True)))
        self.assertFalse(self.account._trx_ai_inbox_capture(self._event(attachment=("audio.ogg", b"x" * 900, "audio/ogg"))))
        self.assertEqual(Inbox.search_count([("wa_account_id", "=", self.account.id)]), 2)
