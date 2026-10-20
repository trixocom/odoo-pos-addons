# Part of trx_purchase_ai_inbox_whatsapp. Author: Trixocom. License: LGPL-3.
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class WhatsappAccount(models.Model):
    _inherit = "whatsapp.account"

    trx_ai_inbox = fields.Boolean(
        string="Leer comprobantes de proveedor",
        help="Cada PDF, foto o Word que llegue a este número entra a la Bandeja de comprobantes de Compras y se "
             "lee con IA, igual que si se subiera a mano. El mensaje sigue llegando al chat como siempre.")
    trx_ai_inbox_count = fields.Integer(string="Comprobantes recibidos", compute="_compute_trx_ai_inbox_count")

    def _compute_trx_ai_inbox_count(self):
        Inbox = self.env["trx.purchase.inbox"].sudo()
        for rec in self:
            rec.trx_ai_inbox_count = Inbox.search_count([("wa_account_id", "=", rec.id)])

    def _process_inbound(self, event):
        message = super()._process_inbound(event)
        if self.trx_ai_inbox:
            self._trx_ai_inbox_capture(event)
        return message

    def _trx_ai_inbox_capture(self, event):
        """Documento entrante → registro en la bandeja. Nunca corta la recepción del mensaje."""
        self.ensure_one()
        if event.get("is_from_me") or event.get("voice") or not event.get("attachment"):
            return False
        name, content, mimetype = event["attachment"]
        Inbox = self.env["trx.purchase.inbox"].sudo()
        try:
            if not Inbox._trx_channel_file_ok(name or "", content, {"mimetype": mimetype}, source="whatsapp"):
                return False
            with self.env.cr.savepoint():
                ref = " ".join(x for x in (event.get("from") or "", event.get("sender_name") or "") if x).strip()
                return Inbox._trx_create_from_files([(name, content, mimetype)], {
                    "source": "whatsapp",
                    "source_ref": ref,
                    "source_subject": (event.get("body") or "")[:250] or False,
                    "wa_account_id": self.id,
                })
        except Exception:  # noqa: BLE001
            _logger.exception("Bandeja de comprobantes: no se pudo registrar el documento recibido por WhatsApp")
            return False

    def action_view_trx_ai_inbox(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("trx_purchase_ai_inbox.action_trx_purchase_inbox")
        action["domain"] = [("wa_account_id", "=", self.id)]
        action["context"] = {}
        return action


class TrxPurchaseInbox(models.Model):
    _inherit = "trx.purchase.inbox"

    wa_account_id = fields.Many2one("whatsapp.account", string="Número de WhatsApp", readonly=True, ondelete="set null")
