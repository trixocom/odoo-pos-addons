from odoo import fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    trx_pos_scanned_qty = fields.Float(
        string="Escaneado en el POS",
        digits="Product Unit",
        copy=False,
        help="Cantidad leída en el POS para esta línea mientras la recepción está en curso.",
    )
