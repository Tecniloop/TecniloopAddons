# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def _generate_journal_entry(
        self, write_off_line_vals=None, force_balance=None, line_ids=None
    ):
        """Keep move.date aligned with payment.date when the payment
        comes from a remittance that uses the due-date rule.

        This is a safety net: Odoo 19 builds the move from ``payment.date``.
        If a core or third-party override ignores that field, we still
        enforce the contract without changing how payments are posted.
        """
        res = super()._generate_journal_entry(
            write_off_line_vals=write_off_line_vals,
            force_balance=force_balance,
            line_ids=line_ids,
        )
        for payment in self.filtered("payment_order_id"):
            payment._sync_move_date_from_payment_order()
        return res

    def _sync_move_date_from_payment_order(self):
        """Single-responsibility helper: align move date if needed."""
        self.ensure_one()
        move = self.move_id
        if not move or move.state != "draft":
            return
        lines = self.payment_line_ids
        if not lines:
            return
        if not lines[:1]._should_use_line_date_as_payment_date():
            return
        target_date = self.date or lines[:1].date
        if target_date and move.date != target_date:
            move.date = target_date
