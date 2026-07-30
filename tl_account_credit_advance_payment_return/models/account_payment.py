# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = "account.payment"

    credit_advance_unpaid_method = fields.Selection(
        related="credit_advance_line_id.unpaid_method",
        string="Charge-back Handling",
    )

    def _get_credit_advance_return_move_lines(self):
        """Journal items a payment return has to match against.

        The same ones the standard matching would find: the credit on the
        customer account of the payment entry, which is what is reconciled with
        the invoice.
        """
        self.ensure_one()
        return self.move_id.line_ids.filtered(
            lambda ml: ml.account_id == self.destination_account_id
        )

    def action_credit_advance_payment_return(self):
        """Draft a payment return with the selected effects already matched."""
        payments = self.filtered(lambda p: p.credit_advance_state in ("assigned", "advanced"))
        if not payments:
            raise UserError(
                self.env._(
                    "Only effects that are assigned or advanced can be returned."
                )
            )
        facilities = payments.credit_advance_line_id
        if len(facilities) > 1:
            raise UserError(
                self.env._(
                    "Select effects of a single credit advance line: the return "
                    "cancels the debt of one facility."
                )
            )
        payment_return = self.env["payment.return"].create(
            {
                "company_id": payments[:1].company_id.id,
                "journal_id": facilities.journal_id.id,
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
                            "reference": payment.payment_order_id.name,
                        },
                    )
                    for payment in payments
                ],
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "payment.return",
            "view_mode": "form",
            "res_id": payment_return.id,
        }
