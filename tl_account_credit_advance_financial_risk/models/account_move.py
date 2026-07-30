# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import models
from odoo.tools import float_compare, formatLang


class AccountMove(models.Model):
    _inherit = "account.move"

    def risk_exception_msg(self):
        """Add the charged-back effects to the risk warning of an invoice.

        A customer can be perfectly within their credit limit and still have
        returned effects: the amount may be small, but the fact that the bank
        gave an effect back is a much stronger signal than the outstanding
        balance. This makes that signal reach the risk wizard shown when the
        invoice is posted.
        """
        res = super().risk_exception_msg()
        company = self.company_id
        if not company.credit_advance_unpaid_warn:
            return res
        partner = self.partner_id.commercial_partner_id
        unpaid = partner.risk_credit_advance_unpaid
        if not unpaid:
            return res
        threshold = company.credit_advance_unpaid_threshold
        currency = partner.risk_currency_id
        if threshold and (
            float_compare(unpaid, threshold, precision_rounding=currency.rounding) <= 0
        ):
            return res
        message = self.env._(
            "This customer has %(amount)s of effects charged back by the bank.\n",
            amount=formatLang(self.env, unpaid, currency_obj=currency),
        )
        return message + (res or "")
