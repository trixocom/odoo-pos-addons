from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon


@tagged("post_install", "-at_install")
class TestCashMoveReasonFrontend(TestPointOfSaleHttpCommon):
    def test_cash_move_reason_tour(self):
        Reason = self.env["pos.cash.move.reason"]
        expense_account = self.env["account.account"].create({
            "code": "TRX5102",
            "name": "Gastos menores de caja",
            "account_type": "expense",
        })
        equity_account = self.env["account.account"].create({
            "code": "TRX3102",
            "name": "Aportes del socio",
            "account_type": "equity",
        })
        expense_reason = Reason.create({
            "name": "Gastos menores",
            "is_income_reason": False,
            "expense_account_id": expense_account.id,
        })
        contribution_reason = Reason.create({
            "name": "Aporte del socio",
            "is_expense_reason": False,
            "income_account_id": equity_account.id,
        })
        # Core only offers cash in/out to PoS managers or users with invoicing rights.
        self.pos_user.write({"group_ids": [(4, self.env.ref("account.group_account_invoice").id)]})
        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.start_pos_tour("trx_cash_move_reason_tour")

        session = self.main_pos_config.current_session_id
        lines = session.statement_line_ids.filtered("trx_pos_cash_move").sorted("id")
        self.assertRecordValues(lines, [
            {"amount": -120.0, "pos_cash_move_reason_id": expense_reason.id},
            {"amount": 300.0, "pos_cash_move_reason_id": contribution_reason.id},
        ])
        self.assertIn("Gastos menores - Librería", lines[0].payment_ref)
        self.assertTrue(lines[1].payment_ref.endswith("Aporte del socio"))
        self.assertIn(expense_account, lines[0].move_id.line_ids.account_id)
        self.assertIn(equity_account, lines[1].move_id.line_ids.account_id)
