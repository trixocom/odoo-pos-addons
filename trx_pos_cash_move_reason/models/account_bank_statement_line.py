from odoo import fields, models


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    pos_cash_move_reason_id = fields.Many2one(
        "pos.cash.move.reason",
        string="Cash In/Out Reason",
        readonly=True,
        index="btree_not_null",
        ondelete="restrict",
    )
    trx_pos_cash_move = fields.Boolean(
        string="PoS Cash In/Out",
        readonly=True,
        index="btree_not_null",
        help="Line created by a cash in/out of a point of sale session.",
    )
