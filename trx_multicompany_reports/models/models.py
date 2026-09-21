# Part of trx_multicompany_reports. Author: Trixocom. License: LGPL-3.
from odoo import models


class PosOrder(models.Model):
    _name = "pos.order"
    _inherit = ["pos.order", "trx.root.company.mixin"]


class PosOrderLine(models.Model):
    _name = "pos.order.line"
    _inherit = ["pos.order.line", "trx.root.company.mixin"]


class PosPayment(models.Model):
    _name = "pos.payment"
    _inherit = ["pos.payment", "trx.root.company.mixin"]


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "trx.root.company.mixin"]


class AccountMoveLine(models.Model):
    _name = "account.move.line"
    _inherit = ["account.move.line", "trx.root.company.mixin"]


class AccountPayment(models.Model):
    _name = "account.payment"
    _inherit = ["account.payment", "trx.root.company.mixin"]


class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = ["stock.picking", "trx.root.company.mixin"]


class StockMove(models.Model):
    _name = "stock.move"
    _inherit = ["stock.move", "trx.root.company.mixin"]


class StockQuant(models.Model):
    _name = "stock.quant"
    _inherit = ["stock.quant", "trx.root.company.mixin"]
