# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import models


class AccountPaymentLine(models.Model):
    _inherit = "account.payment.line"

    def _should_use_line_date_as_payment_date(self):
        """Hook: whether the payment/journal date must follow the line date.

        Default: remittances with execution type "due date".
        Override in extra modules to extend or restrict the rule.
        """
        self.ensure_one()
        order = self.order_id
        return bool(order and order.date_prefered == "due")

    def _get_account_payment_date(self):
        """Date to set on the generated ``account.payment``.

        Returns a date or False to keep the value computed by the parent
        module (today).
        """
        line = self[:1]
        if line and line._should_use_line_date_as_payment_date() and line.date:
            return line.date
        return False

    def _prepare_account_payment_vals(self):
        vals = super()._prepare_account_payment_vals()
        payment_date = self._get_account_payment_date()
        if payment_date:
            vals["date"] = payment_date
        return vals
