# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account_payment_order.tests.test_payment_order_inbound import (
    TestPaymentOrderInboundBase,
)


@tagged("-at_install", "post_install")
class TestCreditAdvance(TestPaymentOrderInboundBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.account_assigned = cls.env["account.account"].create(
            {
                "name": "Assigned receivables",
                "code": "431100",
                "account_type": "asset_receivable",
                "reconcile": True,
                "company_ids": [(6, 0, cls.company.ids)],
            }
        )
        cls.account_unpaid = cls.env["account.account"].create(
            {
                "name": "Unpaid effects",
                "code": "431500",
                "account_type": "asset_receivable",
                "reconcile": True,
                "company_ids": [(6, 0, cls.company.ids)],
            }
        )
        cls.account_debt = cls.env["account.account"].create(
            {
                "name": "Debt for discounted effects",
                "code": "520800",
                "account_type": "liability_current",
                "reconcile": True,
                "company_ids": [(6, 0, cls.company.ids)],
            }
        )
        cls.account_interest = cls.env["account.account"].create(
            {
                "name": "Discount interest",
                "code": "665000",
                "account_type": "expense",
                "company_ids": [(6, 0, cls.company.ids)],
            }
        )
        cls.account_commission = cls.env["account.account"].create(
            {
                "name": "Bank services",
                "code": "626000",
                "account_type": "expense",
                "company_ids": [(6, 0, cls.company.ids)],
            }
        )
        cls.misc_journal = cls.company_data["default_journal_misc"]
        cls.advance_line = cls.env["credit.advance.line"].create(
            {
                "name": "Test discount line",
                "company_id": cls.company.id,
                "journal_id": cls.journal.id,
                "settlement_journal_id": cls.misc_journal.id,
                "account_assigned_id": cls.account_assigned.id,
                "account_unpaid_id": cls.account_unpaid.id,
                "account_debt_id": cls.account_debt.id,
                "account_interest_id": cls.account_interest.id,
                "account_commission_id": cls.account_commission.id,
                "interest_rate": 5.0,
                "commission_rate": 0.5,
            }
        )
        cls.inbound_mode.write(
            {
                "credit_advance": True,
                "credit_advance_line_id": cls.advance_line.id,
            }
        )
        cls.inbound_order.credit_advance_line_id = cls.advance_line

    def _upload_order(self):
        self.inbound_order.draft2open()
        self.inbound_order.open2generated()
        self.inbound_order.generated2uploaded()
        return self.inbound_order.payment_ids

    def _register_advance(self, **values):
        wizard = (
            self.env["credit.advance.funding"]
            .with_context(default_order_id=self.inbound_order.id)
            .create(values)
        )
        wizard.action_confirm()
        return self.inbound_order.advance_move_id

    def test_01_assignment_uses_assigned_account(self):
        """The counterpart of the remittance is 4311, not the bank."""
        payments = self._upload_order()
        self.assertEqual(len(payments), 1)
        payment = payments[0]
        self.assertEqual(payment.outstanding_account_id, self.account_assigned)
        self.assertEqual(payment.credit_advance_state, "assigned")
        assigned_lines = payment.move_id.line_ids.filtered(
            lambda ml: ml.account_id == self.account_assigned
        )
        self.assertEqual(sum(assigned_lines.mapped("debit")), 100.0)
        # the invoice is no longer an open item on the ordinary customer account
        self.assertTrue(self.invoice.line_ids.filtered("reconciled"))

    def test_02_funding_entry(self):
        self._upload_order()
        move = self._register_advance(interest_amount=2.0, commission_amount=1.0)
        self.assertEqual(move.state, "posted")
        debt = move.line_ids.filtered(lambda ml: ml.account_id == self.account_debt)
        self.assertEqual(sum(debt.mapped("credit")), 100.0)
        outstanding = self.advance_line._get_outstanding_account()
        self.assertNotEqual(outstanding, self.journal.default_account_id)
        bank = move.line_ids.filtered(lambda ml: ml.account_id == outstanding)
        self.assertEqual(sum(bank.mapped("debit")), 97.0)
        self.assertEqual(self.inbound_order.advance_net_amount, 97.0)
        self.assertEqual(
            set(self.inbound_order.payment_ids.mapped("credit_advance_state")),
            {"advanced"},
        )
        self.assertEqual(self.advance_line.drawn_amount, 100.0)

    def test_03_settlement_closes_the_effect(self):
        payments = self._upload_order()
        self._register_advance()
        wizard = self.env["credit.advance.settle"].create(
            {
                "credit_advance_line_id": self.advance_line.id,
                "order_id": self.inbound_order.id,
                "journal_id": self.misc_journal.id,
                "payment_ids": [(6, 0, payments.ids)],
            }
        )
        wizard.action_confirm()
        self.assertEqual(payments.credit_advance_state, "settled")
        self.assertEqual(self.advance_line.drawn_amount, 0.0)
        assigned_lines = payments.move_id.line_ids.filtered(
            lambda ml: ml.account_id == self.account_assigned
        )
        self.assertTrue(all(assigned_lines.mapped("reconciled")))

    def test_04_charge_back_returns_the_risk(self):
        payments = self._upload_order()
        self._register_advance()
        wizard = self.env["credit.advance.unpaid"].create(
            {
                "credit_advance_line_id": self.advance_line.id,
                "journal_id": self.journal.id,
                "payment_ids": [(6, 0, payments.ids)],
                "expense_amount": 5.0,
                "expense_account_id": self.account_commission.id,
            }
        )
        wizard.action_confirm()
        move = payments.credit_advance_unpaid_move_id
        self.assertEqual(payments.credit_advance_state, "unpaid")
        bank = move.line_ids.filtered(
            lambda ml: ml.account_id == self.advance_line._get_outstanding_account()
        )
        self.assertEqual(sum(bank.mapped("credit")), 105.0)
        unpaid = move.line_ids.filtered(
            lambda ml: ml.account_id == self.account_unpaid
        )
        self.assertEqual(sum(unpaid.mapped("debit")), 100.0)
        self.assertEqual(self.advance_line.unpaid_amount, 100.0)

    def test_04b_outstanding_account_is_reconcilable(self):
        """The bank leg must be matchable against the statement."""
        account = self.advance_line._get_outstanding_account()
        self.assertTrue(account.reconcile)
        self.assertNotEqual(account, self.journal.default_account_id)

    def test_04c_separate_expenses_leave_the_full_nominal(self):
        """A bank that charges its fees apart must credit the whole nominal."""
        self.advance_line.expense_settlement = "separate"
        self._upload_order()
        wizard = (
            self.env["credit.advance.funding"]
            .with_context(default_order_id=self.inbound_order.id)
            .create({})
        )
        self.assertEqual(wizard.interest_amount, 0.0)
        self.assertEqual(wizard.commission_amount, 0.0)
        self.assertEqual(wizard.net_amount, 100.0)
        wizard.action_confirm()
        outstanding = self.advance_line._get_outstanding_account()
        bank = self.inbound_order.advance_move_id.line_ids.filtered(
            lambda ml: ml.account_id == outstanding
        )
        self.assertEqual(sum(bank.mapped("debit")), 100.0)

    def test_05_limit_blocks_confirmation(self):
        self.advance_line.limit_amount = 50.0
        with self.assertRaises(UserError):
            self.inbound_order.draft2open()

    def test_06_cancel_after_advance_is_blocked(self):
        self._upload_order()
        self._register_advance()
        with self.assertRaises(UserError):
            self.inbound_order.action_cancel()


@tagged("-at_install", "post_install")
class TestCreditAdvanceScheduledSettlement(TestCreditAdvance):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.advance_line.write({"schedule_settlement": True, "recourse_days": 5})

    def test_40_settlement_is_written_in_advance(self):
        payments = self._upload_order()
        self._register_advance()
        move = payments.credit_advance_settle_move_id
        self.assertTrue(move)
        self.assertEqual(move.state, "draft")
        self.assertEqual(move.auto_post, "at_date")
        self.assertEqual(
            move.date, payments.credit_advance_maturity_date + timedelta(days=5)
        )
        # the effect is still advanced until that entry posts
        self.assertEqual(payments.credit_advance_state, "advanced")
        self.assertEqual(self.advance_line.drawn_amount, 100.0)

    def test_41_posting_it_closes_the_effect(self):
        payments = self._upload_order()
        self._register_advance()
        move = payments.credit_advance_settle_move_id
        move._post()
        self.assertEqual(payments.credit_advance_state, "settled")
        self.assertEqual(self.advance_line.drawn_amount, 0.0)
        assigned = payments.move_id.line_ids.filtered(
            lambda ml: ml.account_id == self.account_assigned
        )
        self.assertTrue(all(assigned.mapped("reconciled")))

    def test_42_charge_back_revokes_the_appointment(self):
        payments = self._upload_order()
        self._register_advance()
        move = payments.credit_advance_settle_move_id
        self.env["credit.advance.unpaid"].create(
            {
                "credit_advance_line_id": self.advance_line.id,
                "journal_id": self.journal.id,
                "payment_ids": [(6, 0, payments.ids)],
            }
        ).action_confirm()
        self.assertFalse(move.exists())
        self.assertFalse(payments.credit_advance_settle_move_id)
        self.assertEqual(payments.credit_advance_state, "unpaid")

    def test_43_stale_settlement_refuses_to_post(self):
        """Last line of defence if a charge-back path forgets to revoke."""
        payments = self._upload_order()
        self._register_advance()
        move = payments.credit_advance_settle_move_id
        payments.credit_advance_state = "unpaid"
        with self.assertRaises(UserError):
            move._post()
        self.assertEqual(move.state, "draft")

    def test_44_manual_settlement_refuses_to_duplicate(self):
        payments = self._upload_order()
        self._register_advance()
        wizard = self.env["credit.advance.settle"].create(
            {
                "credit_advance_line_id": self.advance_line.id,
                "journal_id": self.misc_journal.id,
                "payment_ids": [(6, 0, payments.ids)],
            }
        )
        with self.assertRaises(UserError):
            wizard.action_confirm()
