from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    trx_receipt_enabled = fields.Boolean(
        string="Recepción de mercadería",
        help="Muestra el botón 'Recepciones' en el POS para recibir las entradas pendientes "
        "de órdenes de compra del depósito de este punto de venta.",
    )
    trx_receipt_blind = fields.Boolean(
        string="Recepción a ciegas",
        help="Quien recibe sin el permiso 'Recibir mercadería y ver cantidades pedidas' no ve "
        "las cantidades pedidas: solo escanea lo que llegó. Lo faltante queda pendiente.",
    )
    trx_receipt_allowed = fields.Boolean(
        string="Puede recibir mercadería (usuario actual)",
        compute="_compute_trx_receipt_user",
    )
    trx_receipt_blind_for_user = fields.Boolean(
        string="Recepción a ciegas para el usuario actual",
        compute="_compute_trx_receipt_user",
    )

    @api.depends_context("uid")
    @api.depends("trx_receipt_enabled", "trx_receipt_blind")
    def _compute_trx_receipt_user(self):
        user = self.env.user
        allowed = user.has_group("trx_pos_purchase_receipt.group_pos_receipt")
        sees = user.has_group("trx_pos_purchase_receipt.group_pos_receipt_see_expected")
        for config in self:
            config.trx_receipt_allowed = bool(config.trx_receipt_enabled and allowed)
            config.trx_receipt_blind_for_user = bool(config.trx_receipt_blind and not sees)
