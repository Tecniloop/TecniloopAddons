# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.tl_account_credit_advance.tests.test_credit_advance import (
    TestCreditAdvance,
)


@tagged("-at_install", "post_install")
class TestCreditAdvanceRisk(TestCreditAdvance):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref(
            "account_financial_risk.group_account_financial_risk_manager"
        )
        cls.partner.write(
            {
                "risk_invoice_open_include": True,
                "risk_credit_advance_include": True,
                "risk_credit_advance_unpaid_include": True,
            }
        )

    def test_10_risk_moves_from_invoice_to_advance(self):
        """The risk does not vanish when the bank advances the money."""
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.risk_invoice_open, 100.0)
        self._upload_order()
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.risk_invoice_open, 0.0)
        self.assertEqual(self.partner.risk_credit_advance, 100.0)
        # and it is not double counted in the generic bucket
        self.assertEqual(self.partner.risk_account_amount, 0.0)
        self.assertEqual(self.partner.risk_total, 100.0)

    def test_11_non_recourse_removes_the_risk(self):
        self.advance_line.with_recourse = False
        self._upload_order()
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.risk_credit_advance, 0.0)
        self.assertEqual(self.partner.risk_account_amount, 0.0)
        self.assertEqual(self.partner.risk_total, 0.0)

    def test_12_settlement_clears_the_risk(self):
        payments = self._upload_order()
        self._register_advance()
        self.env["credit.advance.settle"].create(
            {
                "credit_advance_line_id": self.advance_line.id,
                "order_id": self.inbound_order.id,
                "journal_id": self.misc_journal.id,
                "payment_ids": [(6, 0, payments.ids)],
            }
        ).action_confirm()
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.risk_credit_advance, 0.0)
        self.assertEqual(self.partner.risk_total, 0.0)

    def test_13_charge_back_moves_risk_to_unpaid(self):
        payments = self._upload_order()
        self._register_advance()
        self.env["credit.advance.unpaid"].create(
            {
                "credit_advance_line_id": self.advance_line.id,
                "journal_id": self.journal.id,
                "payment_ids": [(6, 0, payments.ids)],
            }
        ).action_confirm()
        self.partner.invalidate_recordset()
        self.assertEqual(self.partner.risk_credit_advance, 0.0)
        self.assertEqual(self.partner.risk_credit_advance_unpaid, 100.0)
        self.assertEqual(self.partner.risk_account_amount_unpaid, 0.0)

    def test_14_specific_limit_raises_exception(self):
        self.partner.risk_credit_advance_limit = 50.0
        self._upload_order()
        self.partner.invalidate_recordset()
        self.assertTrue(self.partner.risk_exception)
        self.assertEqual(self.partner.risk_amount_exceeded, 50.0)

    def test_15_risk_check_blocks_confirmation(self):
        self.advance_line.partner_risk_check = "block"
        self.partner.risk_invoice_open_limit = 10.0
        self.partner.invalidate_recordset()
        self.assertTrue(self.partner.risk_exception)
        with self.assertRaises(UserError):
            self.inbound_order.draft2open()

    def test_20_concentration_limit_blocks(self):
        self.advance_line.write(
            {"partner_risk_check": "block", "partner_limit_amount": 50.0}
        )
        with self.assertRaises(UserError):
            self.inbound_order.draft2open()

    def test_21_concentration_limit_percent(self):
        self.advance_line.write(
            {
                "partner_risk_check": "block",
                "limit_amount": 1000.0,
                "partner_limit_percent": 5.0,
            }
        )
        # 5% of 1000 = 50, below the 100 of the remittance
        self.assertEqual(self.advance_line._get_partner_limit(self.partner), 50.0)
        with self.assertRaises(UserError):
            self.inbound_order.draft2open()

    def test_22_credit_limit_is_the_most_restrictive(self):
        self.partner.credit_limit = 30.0
        self.advance_line.write(
            {
                "partner_risk_check": "block",
                "partner_limit_amount": 500.0,
                "partner_limit_use_credit_limit": True,
            }
        )
        self.assertEqual(self.advance_line._get_partner_limit(self.partner), 30.0)
        with self.assertRaises(UserError):
            self.inbound_order.draft2open()

    def test_23_concentration_counts_previous_remittances(self):
        self.advance_line.write(
            {"partner_risk_check": "block", "partner_limit_amount": 150.0}
        )
        # first remittance of 100 goes through
        self.inbound_order.draft2open()
        self.inbound_order.open2generated()
        self.inbound_order.generated2uploaded()
        self.assertEqual(
            self.advance_line._get_partner_drawn()[self.partner], 100.0
        )
        # a second one of 100 would reach 200, over the 150 allowed
        second_invoice = self._create_customer_invoice()
        second_invoice.action_post()
        self.env["account.invoice.payment.line.multi"].with_context(
            active_model="account.move", active_ids=second_invoice.ids
        ).create({}).run()
        second_order = self.payment_order_obj.search(
            [("state", "=", "draft"), ("payment_type", "=", "inbound")], limit=1
        )
        with self.assertRaises(UserError):
            second_order.draft2open()

    def test_24_warn_only_logs(self):
        self.advance_line.write(
            {"partner_risk_check": "warn", "partner_limit_amount": 50.0}
        )
        messages_before = len(self.inbound_order.message_ids)
        self.inbound_order.draft2open()
        self.assertEqual(self.inbound_order.state, "open")
        self.assertGreater(len(self.inbound_order.message_ids), messages_before)

    def test_25_unpaid_effects_warn_on_invoice(self):
        payments = self._upload_order()
        self._register_advance()
        self.env["credit.advance.unpaid"].create(
            {
                "credit_advance_line_id": self.advance_line.id,
                "journal_id": self.journal.id,
                "payment_ids": [(6, 0, payments.ids)],
            }
        ).action_confirm()
        self.company.credit_advance_unpaid_warn = True
        new_invoice = self._create_customer_invoice()
        self.partner.invalidate_recordset()
        self.assertIn("charged back", new_invoice.risk_exception_msg())
        # above the threshold there is no warning
        self.company.credit_advance_unpaid_threshold = 500.0
        self.assertNotIn("charged back", new_invoice.risk_exception_msg() or "")

    def test_26_unpaid_warning_opens_the_risk_wizard(self):
        payments = self._upload_order()
        self._register_advance()
        self.env["credit.advance.unpaid"].create(
            {
                "credit_advance_line_id": self.advance_line.id,
                "journal_id": self.journal.id,
                "payment_ids": [(6, 0, payments.ids)],
            }
        ).action_confirm()
        self.company.credit_advance_unpaid_warn = True
        new_invoice = self._create_customer_invoice()
        self.partner.invalidate_recordset()
        action = new_invoice.action_post()
        self.assertEqual(action.get("res_model"), "partner.risk.exceeded.wiz")
        self.assertEqual(new_invoice.state, "draft")

    def test_27_breakdown_action(self):
        self._upload_order()
        action = self.partner.action_view_credit_advance_risk()
        self.assertEqual(action["res_model"], "account.payment")
        payments = self.env["account.payment"].search(action["domain"])
        self.assertEqual(sum(payments.mapped("credit_advance_amount")), 100.0)
