# Part of trx_pos_interbranch_exchange. Author: Trixocom. License: LGPL-3.
from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = "product.category"

    trx_ibx_exchange_ok = fields.Boolean(
        string="Acepta cambios inter-sucursal",
        default=False,
        help="Los productos de esta categoría pueden cambiarse en cualquier "
        "sucursal de la red (aunque la venta original sea de otra compañía). "
        "Las categorías no tienen compañía: la regla vale para toda la red.",
    )


class ProductTemplate(models.Model):
    _inherit = "product.template"

    trx_ibx_exchange_policy = fields.Selection(
        [
            ("category", "Según la categoría"),
            ("allow", "Siempre acepta cambio"),
            ("deny", "Nunca acepta cambio"),
        ],
        string="Cambio inter-sucursal",
        default="category",
        required=True,
        help="Override por producto del tilde de la categoría.",
    )

    def _trx_ibx_exchange_allowed(self):
        self.ensure_one()
        if self.trx_ibx_exchange_policy == "allow":
            return True
        if self.trx_ibx_exchange_policy == "deny":
            return False
        return bool(self.categ_id.trx_ibx_exchange_ok)
