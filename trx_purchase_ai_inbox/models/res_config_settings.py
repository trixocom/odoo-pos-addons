# Part of trx_purchase_ai_inbox. Author: Trixocom. License: LGPL-3.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    trx_ai_inbox_api_key = fields.Char(string="API key de Anthropic", config_parameter="trx_purchase_ai_inbox.api_key")
    trx_ai_inbox_model = fields.Char(string="Modelo", config_parameter="trx_purchase_ai_inbox.model", default="claude-sonnet-5-5")
    trx_ai_inbox_tolerance = fields.Char(string="Aviso de suba de costo a partir de %", config_parameter="trx_purchase_ai_inbox.price_up_tolerance_pct", default="0.5")
    trx_ai_inbox_auto_scan = fields.Boolean(
        string="Leer automáticamente lo que llega por correo y WhatsApp",
        help="Una tarea programada lee cada pocos minutos los comprobantes nuevos que llegaron por las casillas "
             "de correo y los números de WhatsApp habilitados, y los deja para evaluación.")

    def get_values(self):
        res = super().get_values()
        res["trx_ai_inbox_auto_scan"] = self.env["ir.config_parameter"].sudo().get_param(
            "trx_purchase_ai_inbox.auto_scan", "1") not in ("0", "False", "false", "")
        return res

    def set_values(self):
        super().set_values()
        self.env["ir.config_parameter"].sudo().set_param("trx_purchase_ai_inbox.auto_scan", "1" if self.trx_ai_inbox_auto_scan else "0")
