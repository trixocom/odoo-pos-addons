from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain

ACCOUNT_DOMAIN = [("account_type", "!=", "off_balance")]


class PosCashMoveReason(models.Model):
    _name = "pos.cash.move.reason"
    _description = "PoS Cash In/Out Reason"
    _inherit = ["pos.load.mixin"]
    _order = "sequence, name, id"
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )
    is_income_reason = fields.Boolean(
        string="Cash In",
        default=True,
        help="The reason can be used to put money into the cash register.",
    )
    is_expense_reason = fields.Boolean(
        string="Cash Out",
        default=True,
        help="The reason can be used to take money out of the cash register.",
    )
    income_account_id = fields.Many2one(
        "account.account",
        string="Cash In Account",
        check_company=True,
        domain=ACCOUNT_DOMAIN,
        help="Counterpart account of the journal entry when money is put into the "
        "cash register with this reason.",
    )
    expense_account_id = fields.Many2one(
        "account.account",
        string="Cash Out Account",
        check_company=True,
        domain=ACCOUNT_DOMAIN,
        help="Counterpart account of the journal entry when money is taken out of the "
        "cash register with this reason.",
    )
    pos_config_ids = fields.Many2many(
        "pos.config",
        "pos_cash_move_reason_pos_config_rel",
        "reason_id",
        "config_id",
        string="Points of Sale",
        check_company=True,
        help="Points of sale where the reason is available. Leave empty to make it "
        "available in every point of sale of the company.",
    )
    statement_line_count = fields.Integer(compute="_compute_statement_line_count")

    @api.constrains("is_income_reason", "is_expense_reason", "income_account_id", "expense_account_id")
    def _check_accounts(self):
        for reason in self:
            if not reason.is_income_reason and not reason.is_expense_reason:
                raise ValidationError(
                    _("The reason %s must be usable for cash in, cash out or both.", reason.name)
                )
            if reason.is_income_reason and not reason.income_account_id:
                raise ValidationError(
                    _("The reason %s is used for cash in: set its Cash In Account.", reason.name)
                )
            if reason.is_expense_reason and not reason.expense_account_id:
                raise ValidationError(
                    _("The reason %s is used for cash out: set its Cash Out Account.", reason.name)
                )

    @api.onchange("is_income_reason")
    def _onchange_is_income_reason(self):
        if not self.is_income_reason:
            self.income_account_id = False

    @api.onchange("is_expense_reason")
    def _onchange_is_expense_reason(self):
        if not self.is_expense_reason:
            self.expense_account_id = False

    def _compute_statement_line_count(self):
        groups = self.env["account.bank.statement.line"]._read_group(
            [("pos_cash_move_reason_id", "in", self.ids)],
            ["pos_cash_move_reason_id"],
            ["__count"],
        )
        counts = {reason.id: count for reason, count in groups}
        for reason in self:
            reason.statement_line_count = counts.get(reason.id, 0)

    # ------------------------------------------------------------------
    # Availability helpers
    # ------------------------------------------------------------------
    @api.model
    def _get_available_domain(self, config, direction=None):
        domain = Domain.AND([
            self._check_company_domain(config.company_id),
            [("active", "=", True)],
            ["|", ("pos_config_ids", "=", False), ("pos_config_ids", "in", config.ids)],
        ])
        if direction == "in":
            domain = Domain.AND([domain, [("is_income_reason", "=", True)]])
        elif direction == "out":
            domain = Domain.AND([domain, [("is_expense_reason", "=", True)]])
        return domain

    @api.model
    def _get_available_reasons(self, config, direction=None):
        return self.sudo().search(self._get_available_domain(config, direction))

    def _get_account(self, direction):
        self.ensure_one()
        return self.income_account_id if direction == "in" else self.expense_account_id

    def _check_usable(self, config, direction):
        """Raise if the reason can not be used for ``direction`` in ``config``."""
        self.ensure_one()
        if self not in self._get_available_reasons(config, direction):
            if direction == "in":
                message = _("The reason %(reason)s can not be used for a cash in at %(pos)s.")
            else:
                message = _("The reason %(reason)s can not be used for a cash out at %(pos)s.")
            raise UserError(message % {"reason": self.name, "pos": config.name})
        if not self._get_account(direction):
            raise UserError(_("The reason %s has no account for this kind of cash move.", self.name))

    # ------------------------------------------------------------------
    # PoS data loading
    # ------------------------------------------------------------------
    @api.model
    def _load_pos_data_domain(self, data, config):
        return self._get_available_domain(config)

    @api.model
    def _load_pos_data_fields(self, config):
        return ["id", "name", "sequence", "is_income_reason", "is_expense_reason"]

    def action_view_statement_lines(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "trx_pos_cash_move_reason.action_pos_cash_move_lines"
        )
        action["domain"] = [("pos_cash_move_reason_id", "=", self.id)]
        action["context"] = {}
        return action
