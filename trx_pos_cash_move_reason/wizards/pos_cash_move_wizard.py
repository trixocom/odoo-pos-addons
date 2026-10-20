from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PosCashMoveWizard(models.TransientModel):
    _name = "pos.cash.move.wizard"
    _description = "PoS Cash In/Out from the backend"

    session_id = fields.Many2one("pos.session", required=True, readonly=True, ondelete="cascade")
    currency_id = fields.Many2one(related="session_id.currency_id")
    move_type = fields.Selection(
        [("in", "Cash In"), ("out", "Cash Out")],
        required=True,
        default="out",
    )
    available_reason_ids = fields.Many2many(
        "pos.cash.move.reason", compute="_compute_available_reason_ids"
    )
    reason_id = fields.Many2one(
        "pos.cash.move.reason",
        string="Reason",
        required=True,
        domain="[('id', 'in', available_reason_ids)]",
    )
    account_id = fields.Many2one(
        "account.account", string="Counterpart Account", compute="_compute_account_id"
    )
    amount = fields.Monetary(required=True, currency_field="currency_id")
    note = fields.Char()

    @api.depends("session_id", "move_type")
    def _compute_available_reason_ids(self):
        Reason = self.env["pos.cash.move.reason"]
        for wizard in self:
            if wizard.session_id:
                wizard.available_reason_ids = Reason._get_available_reasons(
                    wizard.session_id.config_id, wizard.move_type
                )
            else:
                wizard.available_reason_ids = Reason

    @api.depends("reason_id", "move_type")
    def _compute_account_id(self):
        for wizard in self:
            wizard.account_id = wizard.reason_id._get_account(wizard.move_type) if wizard.reason_id else False

    @api.onchange("move_type")
    def _onchange_move_type(self):
        if self.reason_id and self.reason_id not in self.available_reason_ids:
            self.reason_id = False

    def _get_label(self):
        self.ensure_one()
        note = (self.note or "").strip()
        return f"{self.reason_id.name} - {note}" if note else self.reason_id.name

    def action_confirm(self):
        self.ensure_one()
        session = self.session_id
        if session.state not in ("opened", "closing_control"):
            raise UserError(_("Cash moves can only be registered on an open session."))
        if self.amount <= 0:
            raise UserError(_("The amount must be greater than zero."))
        translated_type = _("Cash In") if self.move_type == "in" else _("Cash Out")
        extras = {
            "translatedType": translated_type,
            "formattedAmount": self.currency_id.format(self.amount),
            "trx_cash_reason_id": self.reason_id.id,
        }
        session.try_cash_in_out(
            self.move_type, self.amount, self._get_label(), self.env.user.partner_id.id, extras
        )
        session.message_post(
            body=_(
                "%(type)s of %(amount)s registered from the backend. Reason: %(reason)s",
                type=translated_type,
                amount=extras["formattedAmount"],
                reason=self._get_label(),
            )
        )
        return {"type": "ir.actions.act_window_close"}
