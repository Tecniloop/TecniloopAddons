# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PaymentReturn(models.Model):
    _inherit = "payment.return"

    credit_advance_line_id = fields.Many2one(
        comodel_name="credit.advance.line",
        string="Credit Advance Line",
        compute="_compute_credit_advance_line_id",
        store=True,
        help="Facility of the effects returned in this document. Taken from the "
        "matched payments.",
    )
    credit_advance_move_id = fields.Many2one(
        comodel_name="account.move",
        string="Credit Advance Entry",
        readonly=True,
        copy=False,
        help="Entry cancelling the debt with the bank and releasing the "
        "assigned receivables of the returned effects.",
    )

    @api.depends("line_ids.credit_advance_payment_id")
    def _compute_credit_advance_line_id(self):
        for record in self:
            facilities = (
                record.line_ids.credit_advance_payment_id.credit_advance_line_id
            )
            record.credit_advance_line_id = facilities[:1]

    @api.constrains("line_ids")
    def _check_credit_advance_lines(self):
        """One facility per return, without mixing ordinary payments.

        Banks send the returns of a financed remittance on their own, and
        keeping them apart makes the entries readable: mixing would put the debt
        of two different facilities in the same document.
        """
        for record in self:
            facilities = (
                record.line_ids.credit_advance_payment_id.credit_advance_line_id
            )
            if len(facilities) > 1:
                raise ValidationError(
                    self.env._(
                        "The payment return %s mixes effects of several credit "
                        "advance lines. Create one return per facility.",
                        record.name,
                    )
                )
            if facilities and record.line_ids.filtered(
                lambda x: not x.credit_advance_payment_id
            ):
                raise ValidationError(
                    self.env._(
                        "The payment return %s mixes advanced effects with "
                        "ordinary payments. Create separate returns for each.",
                        record.name,
                    )
                )

    def _prepare_move_line(self, move, total_amount):
        """Book the returned amount on the outstanding account of the facility.

        The standard method already avoids the liquidity account, but it takes
        the transit account of the payment method or of the company. With
        several banks that is not enough: each facility has its own transit
        account, and mixing them makes the statement of one bank propose the
        pending entries of another.
        """
        vals = super()._prepare_move_line(move, total_amount)
        if self.credit_advance_line_id:
            vals["account_id"] = self.credit_advance_line_id._get_outstanding_account().id
        return vals

    @api.constrains("journal_id", "line_ids")
    def _check_credit_advance_journal(self):
        """The return has to be booked in the bank that advanced the effects."""
        for record in self.filtered("credit_advance_line_id"):
            facility_journal = record.credit_advance_line_id.journal_id
            if record.journal_id != facility_journal:
                raise ValidationError(
                    self.env._(
                        "The payment return %(name)s returns effects advanced "
                        "by %(facility)s, so it has to be booked in the journal "
                        "%(journal)s.",
                        name=record.name,
                        facility=record.credit_advance_line_id.display_name,
                        journal=facility_journal.display_name,
                    )
                )

    def action_confirm(self):
        """Standard return, plus closing the credit advance cycle.

        The standard entry already debits the customer account, reopening the
        invoice, and credits the bank for the returned amount and its fees. What
        it does not know is that the effect was not an ordinary receipt: it sat
        in the assigned receivables account and it was funded by the bank. A
        second entry releases it and cancels that debt::

            (5208) Debt for discounted effects
                        to (4311) Assigned receivables

        Two entries instead of one on purpose: each of them is balanced and
        readable on its own, and the standard return keeps behaving exactly as
        it does for any other payment.
        """
        advance_lines = self.line_ids.filtered("credit_advance_payment_id")
        res = super().action_confirm()
        if advance_lines:
            self._create_credit_advance_move(advance_lines)
        return res

    def _prepare_credit_advance_move_line_vals(self, return_line):
        self.ensure_one()
        facility = self.credit_advance_line_id
        payment = return_line.credit_advance_payment_id
        amount = self._get_move_amount(return_line)
        label = self.env._(
            "Unpaid effect %(payment)s - %(partner)s",
            payment=payment.display_name,
            partner=return_line.partner_id.name or "",
        )
        return [
            {
                "name": label,
                "account_id": facility.account_assigned_id.id,
                "debit": 0.0,
                "credit": amount,
                "partner_id": return_line.partner_id.id,
            },
            {
                "name": label,
                "account_id": facility.account_debt_id.id,
                "debit": amount,
                "credit": 0.0,
                "partner_id": facility.partner_id.id,
            },
        ]

    def _prepare_credit_advance_move_vals(self, advance_lines):
        self.ensure_one()
        facility = self.credit_advance_line_id
        line_vals = []
        for return_line in advance_lines:
            line_vals += self._prepare_credit_advance_move_line_vals(return_line)
        return {
            "journal_id": facility.settlement_journal_id.id,
            "date": self.date,
            "ref": self.env._("Unpaid effects %s", self.name or ""),
            "company_id": self.company_id.id,
            "credit_advance_line_id": facility.id,
            "credit_advance_move_type": "unpaid",
            "line_ids": [(0, 0, vals) for vals in line_vals],
        }

    def _create_credit_advance_move(self, advance_lines):
        self.ensure_one()
        # The effects will not reach their maturity: drop them from any
        # settlement entry already waiting for that date.
        advance_lines.credit_advance_payment_id._revoke_credit_advance_settlement()
        move = self.env["account.move"].create(
            self._prepare_credit_advance_move_vals(advance_lines)
        )
        move.action_post()
        self.credit_advance_move_id = move
        advance_lines.credit_advance_payment_id.write(
            {
                "credit_advance_state": "unpaid",
                "credit_advance_unpaid_move_id": move.id,
            }
        )
        self._credit_advance_reconcile(move, advance_lines)
        return move

    def _credit_advance_reconcile(self, move, advance_lines):
        """Match what the new entry cancels."""
        self.ensure_one()
        facility = self.credit_advance_line_id
        new_assigned = move.line_ids.filtered(
            lambda ml, a=facility.account_assigned_id: ml.account_id == a
        )
        for return_line in advance_lines:
            payment = return_line.credit_advance_payment_id
            counterpart = new_assigned.filtered(
                lambda ml, p=return_line.partner_id: ml.partner_id == p
                and not ml.reconciled
            )
            to_reconcile = payment._get_credit_advance_assigned_lines() | counterpart
            if len(to_reconcile) > 1:
                to_reconcile.reconcile()
        new_debt = move.line_ids.filtered(
            lambda ml, a=facility.account_debt_id: ml.account_id == a
        )
        orders = advance_lines.credit_advance_payment_id.payment_order_id
        funding_lines = orders.advance_move_id.line_ids.filtered(
            lambda ml, a=facility.account_debt_id: ml.account_id == a
            and not ml.reconciled
        )
        if new_debt and funding_lines:
            (new_debt | funding_lines).reconcile()

    def action_cancel(self):
        for record in self.filtered("credit_advance_move_id"):
            move = record.credit_advance_move_id
            payments = record.line_ids.credit_advance_payment_id
            move.line_ids.remove_move_reconcile()
            record.credit_advance_move_id = False
            move.button_draft()
            move.with_context(force_delete=True).unlink()
            payments.write(
                {
                    "credit_advance_state": "advanced",
                    "credit_advance_unpaid_move_id": False,
                }
            )
        return super().action_cancel()

    def action_view_credit_advance_move(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.credit_advance_move_id.id,
        }


class PaymentReturnLine(models.Model):
    _inherit = "payment.return.line"

    credit_advance_payment_id = fields.Many2one(
        comodel_name="account.payment",
        string="Advanced Effect",
        compute="_compute_credit_advance_payment_id",
        store=True,
        help="Effect of a financed remittance behind the matched journal items.",
    )
    credit_advance_line_id = fields.Many2one(
        related="credit_advance_payment_id.credit_advance_line_id",
        string="Credit Advance Line",
    )

    def _prepare_expense_lines_vals(self, move):
        """Keep the charge-back fees out of the liquidity account.

        The standard method credits ``journal.default_account_id``, which is
        where the statement line itself lands. The bank takes the nominal and
        the fees in a single movement, so both have to sit on the transit
        account for that movement to be matched in one go.
        """
        vals = super()._prepare_expense_lines_vals(move)
        facility = self.credit_advance_line_id
        if not facility:
            return vals
        account = facility._get_outstanding_account()
        for line_vals in vals:
            if line_vals.get("account_id") == self.return_id.journal_id.default_account_id.id:
                line_vals["account_id"] = account.id
        return vals

    @api.depends("move_line_ids")
    def _compute_credit_advance_payment_id(self):
        for line in self:
            payments = line.move_line_ids.payment_id.filtered(
                lambda p: p.credit_advance_line_id
                and p.credit_advance_state in ("assigned", "advanced")
            )
            line.credit_advance_payment_id = payments[:1]
