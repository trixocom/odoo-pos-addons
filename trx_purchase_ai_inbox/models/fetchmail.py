# Part of trx_purchase_ai_inbox. Author: Trixocom. License: LGPL-3.
from odoo import api, fields, models

INBOX_MODEL = "trx.purchase.inbox"


class FetchmailServer(models.Model):
    _inherit = "fetchmail.server"

    trx_ai_inbox = fields.Boolean(
        string="Comprobantes de proveedor", compute="_compute_trx_ai_inbox", inverse="_inverse_trx_ai_inbox",
        help="Cada correo que llegue a esta casilla entra a la Bandeja de comprobantes (un registro por PDF, foto "
             "o Word adjunto) y se lee con IA, igual que si se subiera a mano.")

    @api.depends("object_id")
    def _compute_trx_ai_inbox(self):
        for rec in self:
            rec.trx_ai_inbox = rec.object_id.model == INBOX_MODEL

    def _inverse_trx_ai_inbox(self):
        model = self.env["ir.model"]._get(INBOX_MODEL)
        for rec in self:
            if rec.trx_ai_inbox:
                rec.object_id = model
            elif rec.object_id == model:
                rec.object_id = False
