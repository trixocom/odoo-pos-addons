# Part of trx_product_price_history. Author: Trixocom. License: LGPL-3.
from odoo import api, models

from .price_history import CTX_SKIP


class ProductSupplierinfo(models.Model):
    _inherit = "product.supplierinfo"

    def _trx_history_log(self, old_values, reason=None):
        History = self.env["trx.product.price.history"]
        for rec in self:
            tmpl = rec.product_tmpl_id or rec.product_id.product_tmpl_id
            if not tmpl:
                continue
            History._log(
                tmpl, "supplier_price", old_values.get(rec.id, 0.0), rec.price,
                product=rec.product_id or None, partner=rec.partner_id, supplierinfo=rec,
                company=rec.company_id or None,
                origin=None if self.env.context.get("trx_price_history_origin") else "supplierinfo",
                reason=reason,
            )

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        if not self.env.context.get(CTX_SKIP):
            recs._trx_history_log({}, reason="Alta de precio de proveedor")
        return recs

    def write(self, vals):
        if "price" in vals and not self.env.context.get(CTX_SKIP):
            old = {rec.id: rec.price for rec in self}
            res = super().write(vals)
            self._trx_history_log(old)
            return res
        return super().write(vals)
