# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models
from odoo.exceptions import UserError


class AccountPaymentOrder(models.Model):
    _inherit = "account.payment.order"

    credit_advance = fields.Boolean(
        related="payment_mode_id.credit_advance", store=True, readonly=True
    )
    credit_advance_line_id = fields.Many2one(
        comodel_name="credit.advance.line",
        string="Credit Advance Line",
        check_company=True,
        readonly=True,
        tracking=True,
        help="Facility that finances this remittance.",
    )
    advance_move_id = fields.Many2one(
        comodel_name="account.move",
        string="Advance Entry",
        readonly=True,
        copy=False,
        help="Journal entry booking the funds received from the bank, the "
        "interest, the commission and the financial debt.",
    )
    advance_date = fields.Date(string="Advance Date", readonly=True, copy=False)
    advance_interest = fields.Monetary(
        string="Interest",
        currency_field="company_currency_id",
        readonly=True,
        copy=False,
    )
    advance_commission = fields.Monetary(
        string="Commission",
        currency_field="company_currency_id",
        readonly=True,
        copy=False,
    )
    advance_other_expenses = fields.Monetary(
        string="Other Expenses",
        currency_field="company_currency_id",
        readonly=True,
        copy=False,
    )
    advance_net_amount = fields.Monetary(
        string="Net Advanced",
        compute="_compute_advance_net_amount",
        store=True,
        currency_field="company_currency_id",
    )
    credit_advance_state = fields.Selection(
        selection=[
            ("draft", "Not advanced"),
            ("advanced", "Advanced"),
            ("partial", "Partially settled"),
            ("closed", "Closed"),
        ],
        compute="_compute_credit_advance_state",
        store=True,
        string="Advance Status",
    )

    @api.depends(
        "total_company_currency",
        "advance_interest",
        "advance_commission",
        "advance_other_expenses",
    )
    def _compute_advance_net_amount(self):
        for order in self:
            order.advance_net_amount = (
                order.total_company_currency
                - order.advance_interest
                - order.advance_commission
                - order.advance_other_expenses
            )

    @api.depends("advance_move_id", "payment_ids.credit_advance_state")
    def _compute_credit_advance_state(self):
        for order in self:
            if not order.credit_advance or not order.advance_move_id:
                order.credit_advance_state = "draft"
                continue
            states = set(order.payment_ids.mapped("credit_advance_state"))
            if states == {"advanced"}:
                order.credit_advance_state = "advanced"
            elif "advanced" in states:
                order.credit_advance_state = "partial"
            else:
                order.credit_advance_state = "closed"

    @api.onchange("payment_mode_id")
    def payment_mode_id_change(self):
        res = super().payment_mode_id_change()
        if self.payment_mode_id.credit_advance:
            self.credit_advance_line_id = self.payment_mode_id.credit_advance_line_id
        else:
            self.credit_advance_line_id = False
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("payment_mode_id") and not vals.get("credit_advance_line_id"):
                mode = self.env["account.payment.mode"].browse(vals["payment_mode_id"])
                if mode.credit_advance:
                    vals["credit_advance_line_id"] = mode.credit_advance_line_id.id
        return super().create(vals_list)

    def draft2open(self):
        for order in self.filtered("credit_advance"):
            if not order.credit_advance_line_id:
                raise UserError(
                    self.env._(
                        "The payment mode of the remittance %s is a credit "
                        "advance but no credit advance line is set.",
                        order.name,
                    )
                )
            if order.credit_advance_line_id._check_limit(order.total_company_currency):
                line = order.credit_advance_line_id
                raise UserError(
                    self.env._(
                        "The remittance %(order)s (%(amount)s) exceeds the "
                        "available amount of the credit advance line "
                        "%(line)s (%(available)s).",
                        order=order.name,
                        amount=order.total_company_currency,
                        line=line.name,
                        available=line.available_amount,
                    )
                )
        return super().draft2open()

    def post_and_reconcile(self):
        """Standard behaviour, plus flagging the effects as assigned.

        Nothing else is needed here: the counterpart of the payments is
        redirected to the assigned receivables account (see
        ``account.payment._compute_outstanding_account_id``), so posting the
        payments already produces the reclassification entry

            (4311) Assigned receivables    to    (430) Customers

        and reconciles the customer side with the invoices.
        """
        res = super().post_and_reconcile()
        advance_payments = self.filtered("credit_advance").payment_ids
        advance_payments.filtered(lambda p: not p.credit_advance_state).write(
            {"credit_advance_state": "assigned"}
        )
        return res

    def action_cancel(self):
        posted = self.filtered(lambda o: o.advance_move_id.state == "posted")
        if posted:
            raise UserError(
                self.env._(
                    "The remittance %s has already been advanced by the bank. "
                    "Reset the advance entry before cancelling it.",
                    ", ".join(posted.mapped("name")),
                )
            )
        return super().action_cancel()

    def action_credit_advance_funding(self):
        self.ensure_one()
        if self.state != "uploaded":
            raise UserError(
                self.env._(
                    "Register the advance only once the remittance has been "
                    "sent to the bank (status 'File Uploaded')."
                )
            )
        if self.advance_move_id:
            raise UserError(
                self.env._("This remittance has already been advanced.")
            )
        return {
            "name": self.env._("Register Bank Advance"),
            "type": "ir.actions.act_window",
            "res_model": "credit.advance.funding",
            "view_mode": "form",
            "target": "new",
            "context": {"default_order_id": self.id},
        }

    def action_credit_advance_settle(self):
        self.ensure_one()
        return {
            "name": self.env._("Settle Matured Effects"),
            "type": "ir.actions.act_window",
            "res_model": "credit.advance.settle",
            "view_mode": "form",
            "target": "new",
            "context": {"default_order_id": self.id},
        }

    def action_view_advance_move(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.advance_move_id.id,
        }
