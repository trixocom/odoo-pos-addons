from odoo import _, api, models
from odoo.exceptions import UserError


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _load_pos_data_models(self, config):
        return super()._load_pos_data_models(config) + ["pos.cash.move.reason"]

    def _trx_get_cash_move_reason(self, extras):
        reason_id = (extras or {}).get("trx_cash_reason_id")
        if not reason_id:
            return self.env["pos.cash.move.reason"]
        reason = self.env["pos.cash.move.reason"].sudo().browse(int(reason_id)).exists()
        if not reason:
            raise UserError(_("The selected cash in/out reason no longer exists."))
        return reason

    def try_cash_in_out(self, _type, amount, reason, partner_id, extras):
        direction = "in" if _type == "in" else "out"
        move_reason = self._trx_get_cash_move_reason(extras)
        for session in self.filtered("cash_journal_id"):
            config = session.config_id
            if move_reason:
                move_reason._check_usable(config, direction)
            elif config.trx_cash_reason_required and self.env[
                "pos.cash.move.reason"
            ]._get_available_reasons(config, direction):
                if direction == "in":
                    raise UserError(_("Select a reason for the cash in."))
                raise UserError(_("Select a reason for the cash out."))
        return super().try_cash_in_out(_type, amount, reason, partner_id, extras)

    def _prepare_account_bank_statement_line_vals(self, session, sign, amount, reason, partner_id, extras):
        vals = super()._prepare_account_bank_statement_line_vals(session, sign, amount, reason, partner_id, extras)
        vals["trx_pos_cash_move"] = True
        move_reason = self._trx_get_cash_move_reason(extras)
        if move_reason:
            direction = "in" if sign > 0 else "out"
            vals["counterpart_account_id"] = move_reason._get_account(direction).id
            vals["pos_cash_move_reason_id"] = move_reason.id
        return vals

    def action_trx_cash_move(self):
        self.ensure_one()
        move_type = self.env.context.get("trx_cash_move_type", "out")
        return {
            "name": _("Cash In") if move_type == "in" else _("Cash Out"),
            "type": "ir.actions.act_window",
            "res_model": "pos.cash.move.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_session_id": self.id,
                "default_move_type": move_type,
            },
        }
