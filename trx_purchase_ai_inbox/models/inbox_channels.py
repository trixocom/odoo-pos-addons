# Part of trx_purchase_ai_inbox. Author: Trixocom. License: LGPL-3.
"""Canales de entrada de la bandeja de comprobantes: carga manual, casillas de correo y WhatsApp.

Cualquiera sea el origen, el resultado es el mismo registro ``trx.purchase.inbox`` en estado "Nueva", con el
archivo y el origen (canal, remitente, asunto). Después se lee igual: a mano (botón o selección en la lista)
o en lote (tarea programada), y queda para evaluación.
"""
import base64
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

SOURCES = [
    ("manual", "Carga manual"),
    ("email", "Correo"),
    ("whatsapp", "WhatsApp"),
]
EXTENSIONS = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
}
MIME_EXT = {v: k for k, v in EXTENSIONS.items()}
MIME_EXT["image/jpeg"] = "jpg"
# Las imágenes chicas de un correo son logos / firmas, no comprobantes.
MIN_EMAIL_IMAGE_BYTES = 20 * 1024
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_SCAN_ATTEMPTS = 3


class TrxPurchaseInboxChannels(models.Model):
    _inherit = "trx.purchase.inbox"

    source = fields.Selection(SOURCES, string="Origen", default="manual", required=True, readonly=True, index=True, tracking=True)
    source_ref = fields.Char(string="Recibido de", readonly=True, help="Remitente del correo o número de WhatsApp.")
    source_subject = fields.Char(string="Asunto / mensaje", readonly=True)
    received_date = fields.Datetime(string="Recibido", default=fields.Datetime.now, readonly=True, index=True)
    fetchmail_server_id = fields.Many2one("fetchmail.server", string="Casilla de correo", readonly=True, ondelete="set null")
    duplicate_of_id = fields.Many2one("trx.purchase.inbox", string="Duplicado de", readonly=True, copy=False, ondelete="set null")
    scan_error = fields.Text(string="Error de lectura", readonly=True, copy=False)
    scan_attempts = fields.Integer(string="Intentos de lectura", readonly=True, copy=False)

    # ------------------------------------------------------------ archivos
    @api.model
    def _trx_file_mimetype(self, name, mimetype=None):
        ext = (name or "").lower().rsplit(".", 1)[-1] if "." in (name or "") else ""
        if ext in EXTENSIONS:
            return EXTENSIONS[ext]
        mimetype = (mimetype or "").split(";")[0].strip().lower()
        return mimetype if mimetype in MIME_EXT else False

    @api.model
    def _trx_channel_file_ok(self, name, content, info=None, source="email"):
        """¿El adjunto puede ser un comprobante? PDF, foto o Word; en correo se descartan imágenes embebidas
        (firmas, logos) y las imágenes chicas."""
        info = info or {}
        mimetype = self._trx_file_mimetype(name, info.get("mimetype"))
        if not mimetype or not content:
            return False
        size = len(content)
        if size > MAX_FILE_BYTES:
            return False
        if source == "email" and mimetype.startswith("image/"):
            if info.get("cid") or size < MIN_EMAIL_IMAGE_BYTES:
                return False
        return True

    @api.model
    def _trx_create_from_files(self, files, vals):
        """Crea un registro por archivo [(nombre, contenido bytes, mimetype)] con los mismos datos de origen."""
        records = self.browse()
        for name, content, mimetype in files:
            if isinstance(content, str):
                content = content.encode()
            if not name or "." not in name:
                ext = MIME_EXT.get(self._trx_file_mimetype(name or "", mimetype) or "", "pdf")
                name = "%s.%s" % (name or _("comprobante"), ext)
            records |= self.create(dict(vals, file=base64.b64encode(content), file_name=name))
        origin = dict(SOURCES).get(vals.get("source"), "")
        for rec in records:
            rec.message_post(body=_("Recibido por %(origin)s de %(ref)s%(subject)s.", origin=origin, ref=rec.source_ref or "-",
                                    subject=(" — %s" % rec.source_subject) if rec.source_subject else ""))
        if len(records) > 1:
            for rec in records[1:]:
                rec.message_post(body=_("Llegó junto con %s (mismo mensaje).", records[0].name))
        return records

    # ------------------------------------------------------------ correo
    @api.model
    def message_new(self, msg_dict, custom_values=None):
        """Correo entrante de una casilla marcada "Comprobantes de proveedor": un registro por adjunto válido.
        El correo completo queda en el chatter del primero."""
        vals = dict(custom_values or {})
        vals.update({
            "source": "email",
            "source_ref": msg_dict.get("email_from") or "",
            "source_subject": (msg_dict.get("subject") or "")[:250],
        })
        server_id = self.env.context.get("default_fetchmail_server_id")
        if server_id:
            vals["fetchmail_server_id"] = server_id
        files = []
        for att in msg_dict.get("attachments") or []:
            name, content, info = att[0], att[1], (att[2] if len(att) > 2 and isinstance(att[2], dict) else {})
            content = content.encode() if isinstance(content, str) else content
            if self._trx_channel_file_ok(name, content, info, source="email"):
                files.append((name, content, info.get("mimetype")))
        if not files:
            return self.create(dict(vals, state="rejected",
                                    reject_reason=_("El correo no trae un comprobante adjunto (PDF, foto o Word).")))
        return self._trx_create_from_files(files, vals)[:1]

    # ------------------------------------------------------------ lectura
    def _apply_result(self, data, info):
        res = super()._apply_result(data, info)
        self._trx_check_duplicate()
        return res

    def _trx_check_duplicate(self):
        """El mismo comprobante (proveedor + tipo + número) recibido por otra vía o subido dos veces."""
        for rec in self.filtered(lambda r: r.state != "rejected" and r.partner_id and r.doc_number):
            other = self.search([
                ("id", "!=", rec.id), ("partner_id", "=", rec.partner_id.id), ("doc_number", "=", rec.doc_number),
                ("doc_type", "=", rec.doc_type), ("state", "!=", "rejected"),
            ], order="id", limit=1)
            if other:
                rec.write({"state": "rejected", "duplicate_of_id": other.id,
                           "reject_reason": _("Duplicado: el comprobante %(doc)s ya está en %(other)s (%(origin)s).",
                                              doc=rec.doc_number, other=other.name, origin=dict(SOURCES).get(other.source, ""))})

    def _trx_scan_one(self):
        """Lee un registro sin cortar el lote: si falla, deja el error y vuelve a intentar en la próxima pasada."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                self.action_scan()
            self.write({"scan_error": False})
            return True
        except Exception as e:  # noqa: BLE001 - un comprobante ilegible no frena a los demás
            self.write({"scan_error": str(e)[:1000], "scan_attempts": self.scan_attempts + 1})
            self.message_post(body=_("No se pudo leer (intento %(n)s): %(err)s", n=self.scan_attempts, err=str(e)[:300]))
            return False

    def action_scan_selected(self):
        """Lectura en lote desde la lista (los seleccionados que estén nuevos)."""
        todo = self.filtered(lambda r: r.state == "draft" and r.file)
        ok = sum(1 for rec in todo if rec._trx_scan_one())
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Lectura en lote"), "type": "success" if ok == len(todo) else "warning", "sticky": False,
            "message": _("%(ok)s de %(n)s comprobantes leídos; quedan para evaluación.", ok=ok, n=len(todo)),
            "next": {"type": "ir.actions.act_window_close"},
        }}

    @api.model
    def _cron_scan_pending(self, limit=20):
        """Tarea programada: lee lo que llegó por correo o WhatsApp (y lo que quedó nuevo) y lo deja para evaluación."""
        if self.env["ir.config_parameter"].sudo().get_param("trx_purchase_ai_inbox.auto_scan", "1") in ("0", "False", "false", ""):
            return
        pending = self.search([("state", "=", "draft"), ("file", "!=", False), ("source", "in", ("email", "whatsapp")),
                               ("scan_attempts", "<", MAX_SCAN_ATTEMPTS)], order="received_date, id", limit=limit)
        for rec in pending:
            rec._trx_scan_one()
            if not self.env.context.get("trx_no_commit"):
                self.env.cr.commit()  # cada comprobante queda grabado aunque otro falle
