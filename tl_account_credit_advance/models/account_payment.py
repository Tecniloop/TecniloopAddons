# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    """Within a financed remittance, every payment is an "effect": a single
    receivable assigned to the bank, with its own maturity date and its own
    outcome (settled at maturity or charged back as unpaid).
    """

    _inherit = "account.payment"

    credit_advance_line_id = fields.Many2one(
        comodel_name="credit.advance.line",
        related="payment_order_id.credit_advance_line_id",
        store=True,
        readonly=True,
        string="Credit Advance Line",
    )
    credit_advance_state = fields.Selection(
        selection=[
            ("assigned", "Assigned"),
            ("advanced", "Advanced"),
            ("settled", "Settled"),
            ("unpaid", "Unpaid"),
        ],
        string="Effect Status",
        copy=False,
        readonly=True,
        tracking=True,
        help="Assigned: reclassified to the assigned receivables account.\n"
        "Advanced: the bank has credited the funds.\n"
        "Settled: the customer paid at maturity and the debt with the bank is "
        "cancelled.\n"
        "Unpaid: the bank charged the effect back.",
    )
    credit_advance_amount = fields.Monetary(
        compute="_compute_credit_advance_amount",
        store=True,
        currency_field="company_currency_id",
        string="Nominal Amount",
    )
    credit_advance_maturity_date = fields.Date(
        compute="_compute_credit_advance_maturity_date",
        store=True,
        string="Maturity Date",
    )
    credit_advance_settle_move_id = fields.Many2one(
        comodel_name="account.move", string="Settlement Entry", readonly=True, copy=False
    )
    credit_advance_unpaid_move_id = fields.Many2one(
        comodel_name="account.move", string="Charge-back Entry", readonly=True, copy=False
    )

    @api.depends("payment_line_ids.amount_company_currency", "payment_order_id")
    def _compute_credit_advance_amount(self):
        for payment in self:
            if payment.payment_order_id.credit_advance:
                payment.credit_advance_amount = sum(
                    payment.payment_line_ids.mapped("amount_company_currency")
                )
            else:
                payment.credit_advance_amount = 0.0

    @api.depends("payment_line_ids.ml_maturity_date", "payment_line_ids.date")
    def _compute_credit_advance_maturity_date(self):
        for payment in self:
            dates = [
                line.ml_maturity_date or line.date
                for line in payment.payment_line_ids
                if line.ml_maturity_date or line.date
            ]
            payment.credit_advance_maturity_date = max(dates) if dates else False

    @api.depends(
        "payment_method_line_id",
        "payment_order_id.credit_advance",
        "payment_order_id.credit_advance_line_id",
    )
    def _compute_outstanding_account_id(self):
        """Send the counterpart of a financed remittance to PGC 4311.

        On an ordinary debit order the payment debits the outstanding receipts
        account, i.e. it behaves as if the money were already at the bank. On a
        credit advance the money is not the customer's money yet: the receivable
        merely changes its nature, from an ordinary customer balance to a
        receivable assigned to the bank, and it stays there until maturity.
        """
        res = super()._compute_outstanding_account_id()
        for payment in self:
            line = payment.payment_order_id.credit_advance_line_id
            if payment.payment_order_id.credit_advance and line:
                payment.outstanding_account_id = line.account_assigned_id
        return res

    def _get_credit_advance_assigned_lines(self):
        """Journal items sitting on the assigned receivables account."""
        self.ensure_one()
        account = self.credit_advance_line_id.account_assigned_id
        return self.move_id.line_ids.filtered(
            lambda ml, a=account: ml.account_id == a and not ml.reconciled
        )

    def _check_credit_advance_ready(self, target):
        for payment in self:
            if payment.credit_advance_state not in ("assigned", "advanced"):
                raise UserError(
                    self.env._(
                        "The effect %(name)s cannot be marked as %(target)s "
                        "because its current status is %(state)s.",
                        name=payment.display_name,
                        target=target,
                        state=payment.credit_advance_state or "-",
                    )
                )
            if payment.state not in ("in_process", "paid"):
                raise UserError(
                    self.env._(
                        "The payment %s is not posted.", payment.display_name
                    )
                )

    def _revoke_credit_advance_settlement(self):
        """Cancel the appointment of an effect that will not be collected.

        Only the two journal items of this effect are removed: the entry may
        hold several effects sharing a settlement date, and the rest of them
        still have to be released on that date. Both items balance each other,
        so the entry stays balanced.
        """
        for payment in self:
            move = payment.credit_advance_settle_move_id
            if not move or move.state != "draft":
                continue
            lines = move.line_ids.filtered(
                lambda ml, p=payment: ml.credit_advance_payment_id == p
            )
            payment.credit_advance_settle_move_id = False
            if lines == move.line_ids:
                move.with_context(force_delete=True).unlink()
            else:
                lines.with_context(check_move_validity=False).unlink()

    def action_credit_advance_settle(self):
        scheduled = self.filtered(
            lambda p: p.credit_advance_settle_move_id.state == "draft"
        )
        if scheduled:
            moves = scheduled.credit_advance_settle_move_id
            moves._post()
            return {
                "type": "ir.actions.act_window",
                "res_model": "account.move",
                "view_mode": "form" if len(moves) == 1 else "list,form",
                "res_id": moves.id if len(moves) == 1 else False,
                "domain": [("id", "in", moves.ids)],
            }
        return {
            "name": self.env._("Settle Matured Effects"),
            "type": "ir.actions.act_window",
            "res_model": "credit.advance.settle",
            "view_mode": "form",
            "target": "new",
            "context": {"default_payment_ids": self.ids},
        }

    def action_credit_advance_unpaid(self):
        return {
            "name": self.env._("Register Charge-back"),
            "type": "ir.actions.act_window",
            "res_model": "credit.advance.unpaid",
            "view_mode": "form",
            "target": "new",
            "context": {"default_payment_ids": self.ids},
        }
