from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install")
class TestPosCashMoveReason(TestPoSCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.Reason = cls.env["pos.cash.move.reason"]
        cls.expense_account = cls.env["account.account"].create({
            "code": "TRX5101",
            "name": "Gastos menores de caja",
            "account_type": "expense",
        })
        cls.deposit_account = cls.env["account.account"].create({
            "code": "TRX1105",
            "name": "Valores a depositar",
            "account_type": "asset_current",
        })
        cls.contribution_account = cls.env["account.account"].create({
            "code": "TRX3101",
            "name": "Aportes del socio",
            "account_type": "equity",
        })
        cls.reason_expense = cls.Reason.create({
            "name": "Gastos menores",
            "is_income_reason": False,
            "is_expense_reason": True,
            "expense_account_id": cls.expense_account.id,
        })
        cls.reason_deposit = cls.Reason.create({
            "name": "Depósito bancario",
            "is_income_reason": True,
            "is_expense_reason": True,
            "income_account_id": cls.deposit_account.id,
            "expense_account_id": cls.deposit_account.id,
        })
        cls.reason_contribution = cls.Reason.create({
            "name": "Aporte del socio",
            "is_income_reason": True,
            "is_expense_reason": False,
            "income_account_id": cls.contribution_account.id,
        })

    def _extras(self, reason=None, translated_type="out"):
        extras = {"translatedType": translated_type, "formattedAmount": "$ 0"}
        if reason:
            extras["trx_cash_reason_id"] = reason.id
        return extras

    def _cash_move(self, session, move_type, amount, reason=None, label="Test"):
        before = session.statement_line_ids
        session.try_cash_in_out(move_type, amount, label, False, self._extras(reason, move_type))
        return session.statement_line_ids - before

    # ------------------------------------------------------------------
    def test_reason_constraints(self):
        with self.assertRaises(ValidationError):
            self.Reason.create({
                "name": "Sin cuenta",
                "is_income_reason": True,
                "is_expense_reason": False,
            })
        with self.assertRaises(ValidationError):
            self.Reason.create({
                "name": "Ningún sentido",
                "is_income_reason": False,
                "is_expense_reason": False,
            })
        with Form(self.reason_deposit) as form:
            form.is_income_reason = False
            self.assertFalse(form.income_account_id)
        self.assertFalse(self.reason_deposit.income_account_id)
        self.assertEqual(self.reason_deposit.expense_account_id, self.deposit_account)

    def test_cash_out_posts_to_reason_account(self):
        session = self.open_new_session()
        line = self._cash_move(session, "out", 150.0, self.reason_expense, "Gastos menores - Librería")
        self.assertEqual(len(line), 1)
        self.assertTrue(line.trx_pos_cash_move)
        self.assertEqual(line.pos_cash_move_reason_id, self.reason_expense)
        self.assertEqual(line.amount, -150.0)
        move_lines = line.move_id.line_ids
        cash_account = session.cash_journal_id.default_account_id
        suspense_account = session.cash_journal_id.suspense_account_id
        self.assertRecordValues(
            move_lines.sorted("balance"),
            [
                {"account_id": cash_account.id, "balance": -150.0},
                {"account_id": self.expense_account.id, "balance": 150.0},
            ],
        )
        self.assertNotIn(suspense_account, move_lines.account_id)
        self.assertTrue(line.is_reconciled)
        self.assertEqual(line.move_id.state, "posted")

    def test_cash_in_posts_to_reason_account(self):
        session = self.open_new_session()
        line = self._cash_move(session, "in", 1000.0, self.reason_contribution)
        self.assertRecordValues(
            line.move_id.line_ids.sorted("balance"),
            [
                {"account_id": self.contribution_account.id, "balance": -1000.0},
                {"account_id": session.cash_journal_id.default_account_id.id, "balance": 1000.0},
            ],
        )

    def test_reason_required(self):
        session = self.open_new_session()
        self.assertTrue(self.config.trx_cash_reason_required)
        with self.assertRaises(UserError):
            self._cash_move(session, "out", 10.0)
        self.config.trx_cash_reason_required = False
        line = self._cash_move(session, "out", 10.0)
        self.assertTrue(line.trx_pos_cash_move)
        self.assertFalse(line.pos_cash_move_reason_id)
        self.assertIn(session.cash_journal_id.suspense_account_id, line.move_id.line_ids.account_id)

    def test_no_reasons_keeps_standard_behaviour(self):
        (self.reason_expense | self.reason_deposit | self.reason_contribution).action_archive()
        session = self.open_new_session()
        line = self._cash_move(session, "out", 10.0)
        self.assertFalse(line.pos_cash_move_reason_id)

    def test_reason_direction_and_config_checks(self):
        session = self.open_new_session()
        with self.assertRaises(UserError):
            self._cash_move(session, "out", 10.0, self.reason_contribution)
        with self.assertRaises(UserError):
            self._cash_move(session, "in", 10.0, self.reason_expense)
        self.reason_deposit.pos_config_ids = [Command.set(self.other_currency_config.ids)]
        with self.assertRaises(UserError):
            self._cash_move(session, "out", 10.0, self.reason_deposit)
        self.reason_deposit.pos_config_ids = [Command.set(self.config.ids)]
        line = self._cash_move(session, "out", 10.0, self.reason_deposit)
        self.assertEqual(line.pos_cash_move_reason_id, self.reason_deposit)

    def test_pos_data_loading(self):
        self.reason_deposit.pos_config_ids = [Command.set(self.other_currency_config.ids)]
        session = self.open_new_session()
        self.assertIn("pos.cash.move.reason", session._load_pos_data_models(self.config))
        reasons = self.Reason.search(self.Reason._load_pos_data_domain({}, self.config))
        self.assertIn(self.reason_expense, reasons)
        self.assertIn(self.reason_contribution, reasons)
        self.assertNotIn(self.reason_deposit, reasons)
        data = self.Reason._load_pos_data_read(reasons, self.config)
        self.assertEqual(
            set(data[0]), {"id", "name", "sequence", "is_income_reason", "is_expense_reason"}
        )

    def test_close_session_with_cash_moves(self):
        session = self.open_new_session(opening_cash=500.0)
        self._cash_move(session, "out", 200.0, self.reason_deposit)
        self._cash_move(session, "in", 50.0, self.reason_contribution)
        expected = session.get_closing_control_data()["default_cash_details"]["amount"]
        self.assertAlmostEqual(expected, 350.0)
        session.post_closing_cash_details(expected)
        session.update_closing_control_state_session(False)
        self.assertEqual(session.close_session_from_ui(), {"successful": True})
        self.assertEqual(session.state, "closed")
        self.assertEqual(session.cash_register_difference, 0)
        reasons = session.statement_line_ids.filtered("trx_pos_cash_move").pos_cash_move_reason_id
        self.assertEqual(reasons, self.reason_deposit | self.reason_contribution)
        deposit_balance = sum(
            self.env["account.move.line"]
            .search([("account_id", "=", self.deposit_account.id), ("parent_state", "=", "posted")])
            .mapped("balance")
        )
        self.assertAlmostEqual(deposit_balance, 200.0)
        self.assertEqual(self.reason_deposit.statement_line_count, 1)

    def test_backend_wizard(self):
        session = self.open_new_session()
        action = session.with_context(trx_cash_move_type="out").action_trx_cash_move()
        self.assertEqual(action["res_model"], "pos.cash.move.wizard")
        wizard_form = Form(self.env["pos.cash.move.wizard"].with_context(action["context"]))
        self.assertEqual(wizard_form.move_type, "out")
        self.assertNotIn(self.reason_contribution, wizard_form.available_reason_ids)
        wizard_form.reason_id = self.reason_expense
        self.assertEqual(wizard_form.account_id, self.expense_account)
        wizard_form.amount = 75.0
        wizard_form.note = "Remis"
        wizard = wizard_form.save()
        wizard.action_confirm()
        line = session.statement_line_ids.filtered("trx_pos_cash_move")
        self.assertEqual(line.amount, -75.0)
        self.assertEqual(line.pos_cash_move_reason_id, self.reason_expense)
        self.assertIn("Gastos menores - Remis", line.payment_ref)
        self.assertIn(self.expense_account, line.move_id.line_ids.account_id)

    def test_backend_wizard_rejects_bad_amount(self):
        session = self.open_new_session()
        wizard = self.env["pos.cash.move.wizard"].create({
            "session_id": session.id,
            "move_type": "out",
            "reason_id": self.reason_expense.id,
            "amount": 0.0,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()

    def test_cashier_without_accounting_rights(self):
        """A cashier (PoS user + invoicing rights, as required by core) can use reasons
        even without read access to accounts."""
        cashier = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Cajero",
            "login": "trx_cajero",
            "company_id": self.company.id,
            "company_ids": [Command.set(self.company.ids)],
            "group_ids": [Command.set([
                self.env.ref("base.group_user").id,
                self.env.ref("point_of_sale.group_pos_user").id,
                self.env.ref("account.group_account_invoice").id,
            ])],
        })
        session = self.open_new_session()
        session.with_user(cashier).try_cash_in_out(
            "out", 20.0, "Gastos menores", cashier.partner_id.id, self._extras(self.reason_expense)
        )
        line = session.statement_line_ids.filtered("trx_pos_cash_move")
        self.assertEqual(line.pos_cash_move_reason_id, self.reason_expense)
