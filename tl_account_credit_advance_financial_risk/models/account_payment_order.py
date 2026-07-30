# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class AccountPaymentOrder(models.Model):
    _inherit = "account.payment.order"

    def _get_credit_advance_risky_partners(self):
        """Customers in the remittance whose financial risk is exceeded."""
        self.ensure_one()
        partners = self.payment_line_ids.partner_id.commercial_partner_id
        return partners.filtered("risk_exception")

    def _get_credit_advance_partner_amounts(self):
        """Nominal of this remittance per commercial partner."""
        self.ensure_one()
        amounts = {}
        for payline in self.payment_line_ids:
            commercial = payline.partner_id.commercial_partner_id
            amounts[commercial] = (
                amounts.get(commercial, 0.0) + payline.amount_company_currency
            )
        return amounts

    def _get_credit_advance_concentration_warnings(self):
        """Customers that would go over their limit on the facility.

        The limit is the most restrictive of the caps configured on the
        facility, including the credit limit of the customer when that option
        is enabled. What is already assigned from previous remittances counts
        too.
        """
        self.ensure_one()
        line = self.credit_advance_line_id
        amounts = self._get_credit_advance_partner_amounts()
        if not amounts:
            return []
        partners = self.env["res.partner"].browse(
            [partner.id for partner in amounts]
        )
        drawn = line._get_partner_drawn(partners)
        rounding = line.currency_id.rounding
        warnings = []
        for partner, amount in amounts.items():
            limit = line._get_partner_limit(partner)
            if not limit:
                continue
            total = drawn.get(partner, 0.0) + amount
            if float_compare(total, limit, precision_rounding=rounding) > 0:
                warnings.append(
                    self.env._(
                        "%(partner)s: %(total)s assigned against a limit of "
                        "%(limit)s",
                        partner=partner.display_name,
                        total=total,
                        limit=limit,
                    )
                )
        return warnings

    def draft2open(self):
        for order in self.filtered(
            lambda o: o.credit_advance
            and o.credit_advance_line_id.partner_risk_check != "none"
        ):
            messages = []
            risky = order._get_credit_advance_risky_partners()
            if risky:
                messages.append(
                    self.env._(
                        "Financial risk exceeded: %s",
                        ", ".join(risky.mapped("display_name")),
                    )
                )
            concentration = order._get_credit_advance_concentration_warnings()
            if concentration:
                messages.append(
                    self.env._("Over the limit of the credit advance line:")
                    + "\n"
                    + "\n".join(concentration)
                )
            if not messages:
                continue
            body = "\n".join(messages)
            if order.credit_advance_line_id.partner_risk_check == "block":
                raise UserError(
                    self.env._(
                        "The remittance %(order)s cannot be confirmed:\n\n"
                        "%(body)s\n\n"
                        "Remove those transactions from the remittance, raise "
                        "the limits, or set the risk check of the credit "
                        "advance line to a warning.",
                        order=order.name,
                        body=body,
                    )
                )
            order.message_post(body=body.replace("\n", "<br/>"))
        return super().draft2open()
