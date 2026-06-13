from odoo import api, fields, models


class PosPromotion(models.Model):
    """Promoción de POS: descuento de la casa + reintegro del banco.

    El **descuento de la casa** se aplica como descuento general sobre la orden
    (una línea negativa única). El **reintegro del banco** no se descuenta: se
    informa en el ticket y dispara la nota de crédito fiscal del importe
    devuelto (para no pagar el IVA de esa devolución).
    """

    _name = "pos.promotion"
    _description = "Promoción de Punto de Venta"
    _inherit = ["pos.load.mixin"]
    _order = "sequence, name"

    name = fields.Char(
        string="Nombre de la promoción",
        required=True,
        translate=False,
        help="Se muestra en el ticket y etiqueta la línea de descuento de la casa.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    house_discount_pct = fields.Float(
        string="Descuento de la casa (%)",
        digits=(16, 4),
        default=0.0,
        help="Porcentaje que descuenta la casa sobre el total de la orden. "
        "Se aplica como una línea de descuento negativa etiquetada con la promo. "
        "Es lo que el cliente paga de menos.",
    )

    bank_discount_pct = fields.Float(
        string="Devolución del banco (%)",
        digits=(16, 4),
        default=0.0,
        help="Porcentaje que el banco le reintegra al cliente. NO se descuenta "
        "del total: solo se informa en el ticket y genera la nota de crédito "
        "fiscal del importe devuelto.",
    )

    bank_base = fields.Selection(
        selection=[
            ("total_incl", "Total cobrado (IVA incluido)"),
            ("untaxed", "Neto gravado (sin IVA)"),
        ],
        string="Base de la devolución",
        default="total_incl",
        required=True,
        help="Sobre qué importe de la factura se calcula la devolución del banco.",
    )

    bank_nc_with_iva = fields.Boolean(
        string="NC discrimina IVA",
        default=True,
        help="Si está tildado, la nota de crédito de la devolución bancaria "
        "discrimina IVA (reduce el débito fiscal: efecto 'no pagar el IVA de la "
        "devolución'). Si no, la NC se emite sin IVA.",
    )

    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )

    @api.model
    def _load_pos_data_domain(self, data, config):
        return [
            ("active", "=", True),
            ("company_id", "in", config.company_id.ids + [False]),
        ]

    @api.model
    def _load_pos_data_fields(self, config):
        return [
            "id",
            "name",
            "house_discount_pct",
            "bank_discount_pct",
            "bank_base",
            "bank_nc_with_iva",
        ]
