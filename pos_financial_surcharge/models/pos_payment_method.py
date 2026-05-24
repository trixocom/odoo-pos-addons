from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    available_card_ids = fields.Many2many(
        "account.card",
        string="Available Cards",
        help="Tarjetas que el cajero podrá ofrecer cuando este método de pago "
        "esté configurado como 'Card financial surcharge'.",
    )

    def _get_payment_terminal_selection(self):
        return super()._get_payment_terminal_selection() + [
            ("financial_surcharge", "Card financial surcharge")
        ]

    @api.constrains("use_payment_terminal", "available_card_ids", "company_id")
    def _check_financial_surcharge_product(self):
        """Si el método usa el terminal de recargo financiero, la company
        DEBE tener `product_surcharge_id` configurado. Si no, no permitimos
        guardar (fix del bug #3 de 18: el JS reventaba en runtime sin guard).
        """
        for rec in self.filtered(lambda m: m.use_payment_terminal == "financial_surcharge"):
            company = rec.company_id or self.env.company
            if not company.product_surcharge_id:
                raise ValidationError(
                    "El método de pago '%s' está configurado como 'Card financial "
                    "surcharge' pero la empresa '%s' no tiene definido el producto "
                    "de recargo financiero. Configurálo en Punto de Venta → "
                    "Configuración → Ajustes → 'Producto para recargo financiero' "
                    "antes de activar este método de pago."
                    % (rec.name, company.display_name)
                )

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ["available_card_ids"]

    @api.model
    def _load_pos_data_domain(self, data, config):
        """Si la company del POS no tiene product_surcharge_id configurado,
        ocultamos los métodos de pago de tipo financial_surcharge para evitar
        que el cajero los elija y dispare un error en runtime.
        (Bloqueo del método sin producto, según decisión del proyecto.)
        """
        domain = super()._load_pos_data_domain(data, config)
        if not config.company_id.product_surcharge_id:
            domain = list(domain) + [("use_payment_terminal", "!=", "financial_surcharge")]
        return domain
