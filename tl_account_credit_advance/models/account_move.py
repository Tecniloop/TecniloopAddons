# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models
from odoo.exceptions import UserError


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    credit_advance_payment_id = fields.Many2one(
        comodel_name="account.payment",
        string="Advanced Effect",
        index="btree_not_null",
        copy=False,
        help="Effect this journal item releases. It is what allows a scheduled "
        "settlement entry to be revoked effect by effect.",
    )


class AccountMove(models.Model):
    _inherit = "account.move"

    credit_advance_line_id = fields.Many2one(
        comodel_name="credit.advance.line",
        string="Credit Advance Line",
        readonly=True,
        copy=False,
        index="btree_not_null",
    )
    credit_advance_move_type = fields.Selection(
        selection=[
            ("funding", "Bank Advance"),
            ("settlement", "Maturity Settlement"),
            ("unpaid", "Charge-back"),
        ],
        string="Credit Advance Entry Type",
        readonly=True,
        copy=False,
    )

    def _post(self, soft=True):
        """Never release an effect that is no longer there to be released.

        A settlement entry may have been written weeks in advance and set to
        post itself at the end of the recourse period. Everything that can
        happen in between -- a charge-back, a cancelled advance -- revokes it,
        but this is the last line of defence: if the effect is not advanced any
        more when the entry is due, the entry stays in draft and someone has to
        look at it, instead of cancelling a debt that is still owed.
        """
        settlements = self.filtered(
            lambda m: m.credit_advance_move_type == "settlement"
            and m.state == "draft"
        )
        settlements._check_credit_advance_settlement()
        posted = super()._post(soft=soft)
        for move in posted.filtered(
            lambda m: m.credit_advance_move_type == "settlement"
        ):
            move._credit_advance_settlement_post_process()
        return posted

    def _check_credit_advance_settlement(self):
        for move in self:
            stale = move.line_ids.credit_advance_payment_id.filtered(
                lambda p: p.credit_advance_state != "advanced"
            )
            if stale:
                raise UserError(
                    self.env._(
                        "The settlement entry %(move)s cannot be posted because "
                        "these effects are no longer advanced: %(effects)s.\n\n"
                        "They were probably charged back. Remove them from the "
                        "entry, or cancel it if none of its effects is due.",
                        move=move.display_name,
                        effects=", ".join(stale.mapped("display_name")),
                    )
                )

    def _credit_advance_settlement_post_process(self):
        """Match what the settlement cancels and close the effects.

        Done here and not in the wizard so that it happens whoever posts the
        entry: the user, the scheduled action of Odoo, or a manual settlement.
        """
        self.ensure_one()
        facility = self.credit_advance_line_id
        payments = self.line_ids.credit_advance_payment_id
        if not facility or not payments:
            return
        for payment in payments:
            new_assigned = self.line_ids.filtered(
                lambda ml, p=payment, a=facility.account_assigned_id: (
                    ml.credit_advance_payment_id == p and ml.account_id == a
                )
            )
            to_reconcile = (
                payment._get_credit_advance_assigned_lines() | new_assigned
            )
            if len(to_reconcile) > 1:
                to_reconcile.reconcile()
        new_debt = self.line_ids.filtered(
            lambda ml, a=facility.account_debt_id: ml.account_id == a
        )
        funding_lines = payments.payment_order_id.advance_move_id.line_ids.filtered(
            lambda ml, a=facility.account_debt_id: ml.account_id == a
            and not ml.reconciled
        )
        if new_debt and funding_lines:
            (new_debt | funding_lines).reconcile()
        payments.write(
            {
                "credit_advance_state": "settled",
                "credit_advance_settle_move_id": self.id,
            }
        )

    def button_draft(self):
        """Keep the effect status consistent when an entry is reset."""
        advance_moves = self.filtered("credit_advance_move_type")
        res = super().button_draft()
        for move in advance_moves:
            if move.credit_advance_move_type == "funding":
                move.payment_order_id.payment_ids.filtered(
                    lambda p: p.credit_advance_state == "advanced"
                ).write({"credit_advance_state": "assigned"})
                move.payment_order_id.write(
                    {"advance_move_id": False, "advance_date": False}
                )
            else:
                payments = self.env["account.payment"].search(
                    [
                        "|",
                        ("credit_advance_settle_move_id", "=", move.id),
                        ("credit_advance_unpaid_move_id", "=", move.id),
                    ]
                )
                payments.write(
                    {
                        "credit_advance_state": "advanced",
                        "credit_advance_unpaid_move_id": False,
                    }
                )
        return res
