# Part of trx_product_price_history. Author: Trixocom. License: LGPL-3.
from odoo import models

from .price_history import CTX_SKIP


class ProductProduct(models.Model):
    _inherit = "product.product"

    def write(self, vals):
        if "standard_price" in vals and not self.env.context.get(CTX_SKIP):
            old = {rec.id: rec.standard_price for rec in self}
            res = super().write(vals)
            History = self.env["trx.product.price.history"]
            origin = "planned" if self.env.context.get("bypass_base_automation") else None
            reason = "Sincronización con el costo de reposición" if origin else None
            for rec in self:
                History._log(
                    rec.product_tmpl_id, "standard_price", old[rec.id], rec.standard_price,
                    product=rec, company=self.env.company, origin=origin, reason=reason,
                )
            return res
        return super().write(vals)
