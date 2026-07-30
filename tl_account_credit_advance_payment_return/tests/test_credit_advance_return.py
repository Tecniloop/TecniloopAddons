# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo.tests import tagged

from odoo.addons.tl_account_credit_advance.tests.test_credit_advance import (
    TestCreditAdvance,
)


@tagged("-at_install", "post_install")
class TestCreditAdvanceReturn(TestCreditAdvance):
    def _create_return(self, payments, expense_amount=0.0):
        return self.env["payment.return"].create(
            {
                "company_id": self.company.id,
                "journal_id": self.journal.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "partner_id": payment.partner_id.id,
                            "move_line_ids": [
                                (
                                    6,
                                    0,
                                    payment._get_credit_advance_return_move_lines().ids,
                                )
                            ],
                            "amount": payment.credit_advance_amount,
                            "expense_amount": expense_amount,
                            "expense_account": self.account_commission.id
                            if expense_amount
                            else False,
                        },
                    )
                    for payment in payments
                ],
            }
        )

    def test_30_return_line_detects_the_effect(self):
        payments = self._upload_order()
        self._register_advance()
        payment_return = self._create_return(payments)
        self.assertEqual(
            payment_return.line_ids.credit_advance_payment_id, payments[0]
        )
        self.assertEqual(payment_return.credit_advance_line_id, self.advance_line)

    def test_31_confirm_closes_the_advance(self):
        payments = self._upload_order()
        self._register_advance()
        payment_return = self._create_return(payments)
        payment_return.action_confirm()
        self.assertEqual(payment_return.state, "done")
        self.assertEqual(payments.credit_advance_state, "unpaid")
        move = payment_return.credit_advance_move_id
        self.assertEqual(move.state, "posted")
        assigned = move.line_ids.filtered(
            lambda ml: ml.account_id == self.account_assigned
        )
        debt = move.line_ids.filtered(lambda ml: ml.account_id == self.account_debt)
        self.assertEqual(sum(assigned.mapped("credit")), 100.0)
        self.assertEqual(sum(debt.mapped("debit")), 100.0)
        # the assigned effect of the remittance is cancelled
        self.assertTrue(
            all(
                payments.move_id.line_ids.filtered(
                    lambda ml: ml.account_id == self.account_assigned
                ).mapped("reconciled")
            )
        )
        # and the facility no longer has it drawn
        self.assertEqual(self.advance_line.drawn_amount, 0.0)
        self.assertEqual(self.advance_line.unpaid_amount, 100.0)

    def test_32_invoice_is_reopened(self):
        payments = self._upload_order()
        self._register_advance()
        self._create_return(payments).action_confirm()
        self.assertTrue(self.invoice.returned_payment)
        self.assertNotEqual(self.invoice.payment_state, "paid")

    def test_33_expenses_go_to_the_standard_entry(self):
        payments = self._upload_order()
        self._register_advance()
        payment_return = self._create_return(payments, expense_amount=5.0)
        payment_return.action_confirm()
        expense = payment_return.move_id.line_ids.filtered(
            lambda ml: ml.account_id == self.account_commission
        )
        self.assertEqual(sum(expense.mapped("debit")), 5.0)

    def test_34_cancel_reverts_the_effect(self):
        payments = self._upload_order()
        self._register_advance()
        payment_return = self._create_return(payments)
        payment_return.action_confirm()
        payment_return.action_cancel()
        self.assertEqual(payment_return.state, "cancelled")
        self.assertFalse(payment_return.credit_advance_move_id)
        self.assertEqual(payments.credit_advance_state, "advanced")
        self.assertEqual(self.advance_line.drawn_amount, 100.0)

    def test_35_action_from_the_effect(self):
        payments = self._upload_order()
        self._register_advance()
        action = payments.action_credit_advance_payment_return()
        self.assertEqual(action["res_model"], "payment.return")
        payment_return = self.env["payment.return"].browse(action["res_id"])
        self.assertEqual(payment_return.line_ids.credit_advance_payment_id, payments)

    def test_36_default_method_is_the_payment_return(self):
        self.assertEqual(self.advance_line.unpaid_method, "return")

    def test_37_bank_side_sits_on_the_outstanding_account(self):
        """The whole movement of the bank must be matchable in one go."""
        payments = self._upload_order()
        self._register_advance()
        payment_return = self._create_return(payments, expense_amount=5.0)
        payment_return.action_confirm()
        outstanding = self.advance_line._get_outstanding_account()
        liquidity = payment_return.move_id.line_ids.filtered(
            lambda ml: ml.account_id == self.journal.default_account_id
        )
        self.assertFalse(liquidity, "Nothing may hit the liquidity account")
        bank_side = payment_return.move_id.line_ids.filtered(
            lambda ml: ml.account_id == outstanding
        )
        self.assertEqual(sum(bank_side.mapped("credit")), 105.0)

    def test_38_journal_must_be_the_one_of_the_facility(self):
        from odoo.exceptions import ValidationError

        payments = self._upload_order()
        self._register_advance()
        other_journal = self.env["account.journal"].create(
            {
                "name": "Other bank",
                "type": "bank",
                "code": "OTHBK",
                "company_id": self.company.id,
            }
        )
        with self.assertRaises(ValidationError):
            self._create_return(payments).write({"journal_id": other_journal.id})
