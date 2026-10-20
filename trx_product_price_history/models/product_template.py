# Part of trx_product_price_history. Author: Trixocom. License: LGPL-3.
from odoo import api, fields, models
from odoo.tools import float_is_zero

from .price_history import CTX_SKIP


class ProductTemplate(models.Model):
    _inherit = "product.template"

    trx_price_history_ids = fields.One2many(
        "trx.product.price.history", "product_tmpl_id", string="Historial de precios"
    )
    trx_price_history_count = fields.Integer(compute="_compute_trx_price_history")
    trx_pvp_previous = fields.Float(
        string="PVP anterior", compute="_compute_trx_price_history", digits="Product Price",
        help="PVP que tenía el artículo antes del último cambio registrado.",
    )
    trx_pvp_previous_date = fields.Datetime(string="PVP anterior vigente hasta", compute="_compute_trx_price_history")

    def _compute_trx_price_history(self):
        History = self.env["trx.product.price.history"].sudo()
        groups = History._read_group(
            [("product_tmpl_id", "in", self.ids)], groupby=["product_tmpl_id"], aggregates=["__count"]
        )
        counts = {tmpl.id: count for tmpl, count in groups}
        for rec in self:
            rec.trx_price_history_count = counts.get(rec.id, 0)
            last = History.search(
                [("product_tmpl_id", "=", rec.id), ("price_type", "=", "list_price")], limit=1
            )
            rec.trx_pvp_previous = last.old_value if last else 0.0
            rec.trx_pvp_previous_date = last.date if last else False

    def write(self, vals):
        if "list_price" in vals and not self.env.context.get(CTX_SKIP):
            old = {rec.id: rec.list_price for rec in self}
            res = super().write(vals)
            History = self.env["trx.product.price.history"]
            for rec in self:
                History._log(rec, "list_price", old[rec.id], rec.list_price)
            return res
        return super().write(vals)

    def _update_prices_from_planned(self):
        """product_planned_price actualiza list_price por SQL: registramos el cambio antes."""
        if not self.env.context.get(CTX_SKIP):
            prec = self.env["decimal.precision"].precision_get("Product Price")
            History = self.env["trx.product.price.history"]
            for rec in self.with_context(prefetch_fields=False):
                if (
                    rec.list_price_type
                    and rec.computed_list_price
                    and not float_is_zero(rec.computed_list_price - rec.list_price, precision_digits=prec)
                ):
                    History._log(rec, "list_price", rec.list_price, rec.computed_list_price,
                                 origin="planned", reason="Precio planificado")
        return super()._update_prices_from_planned()

    def action_view_trx_price_history(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("trx_product_price_history.action_trx_product_price_history")
        action["domain"] = [("product_tmpl_id", "=", self.id)]
        action["context"] = {"default_product_tmpl_id": self.id, "search_default_group_price_type": 1}
        return action
