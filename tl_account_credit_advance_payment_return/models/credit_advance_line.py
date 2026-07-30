# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class CreditAdvanceLine(models.Model):
    _inherit = "credit.advance.line"

    unpaid_method = fields.Selection(
        selection=[
            ("return", "Payment return"),
            ("wizard", "Charge-back wizard"),
        ],
        default="return",
        required=True,
        string="Charge-back Handling",
        help="How the unpaid effects of this facility are processed.\n\n"
        "Payment return: uses the payment returns of "
        "account_payment_return. The original invoice is reopened and flagged "
        "as returned, the return reason is recorded, and the bank file of "
        "returns can be imported. This is the recommended option.\n\n"
        "Charge-back wizard: the simpler built-in wizard, which moves the debt "
        "to the unpaid effects account (PGC 4315) instead of reopening the "
        "invoice.",
    )

    def _get_effects_to_settle_domain(self, date_reference):
        """Never settle an effect that has a return under way.

        A draft or imported return means the bank has already given the effect
        back and someone is processing it: settling it would cancel a debt that
        is about to be charged instead.
        """
        domain = super()._get_effects_to_settle_domain(date_reference)
        pending = self.env["payment.return.line"].search(
            [
                ("credit_advance_payment_id", "!=", False),
                ("return_id.state", "in", ("draft", "imported")),
            ]
        )
        if pending:
            domain.append(
                ("id", "not in", pending.credit_advance_payment_id.ids)
            )
        return domain
