from odoo import fields, models


class PosPayment(models.Model):
    _inherit = "pos.payment"

    card_installment_pos_id = fields.Integer(
        string="Plan de cuotas (id POS)",
        copy=False,
        help="ID del plan de cuotas (account.card.installment) elegido al cobrar "
        "en el POS.\n\n"
        "Es un campo escalar a propósito: el frontend del POS solo puede escribir "
        "campos REALES del modelo (related_models lanza \"The field 'X' does not "
        "exist in model 'Y'\" si le asignás una propiedad suelta, y deja el POS en "
        "blanco). Como `pos.payment` no overridea `_load_pos_data_fields`, carga "
        "todos sus campos por default y este viaja solo al frontend y de vuelta.",
    )
