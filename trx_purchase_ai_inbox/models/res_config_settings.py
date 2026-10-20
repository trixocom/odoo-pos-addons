# Part of trx_purchase_ai_inbox. Author: Trixocom. License: LGPL-3.
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    trx_ai_inbox_api_key = fields.Char(string="API key de Anthropic", config_parameter="trx_purchase_ai_inbox.api_key")
    trx_ai_inbox_model = fields.Char(string="Modelo", config_parameter="trx_purchase_ai_inbox.model", default="claude-sonnet-5-5")
    trx_ai_inbox_tolerance = fields.Char(string="Aviso de suba de costo a partir de %", config_parameter="trx_purchase_ai_inbox.price_up_tolerance_pct", default="0.5")
