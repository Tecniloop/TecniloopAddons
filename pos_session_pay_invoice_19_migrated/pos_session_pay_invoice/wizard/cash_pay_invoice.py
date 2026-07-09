# Copyright (C) 2017 Creu Blanca
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html).

from odoo import api, fields, models


class CashPayInvoice(models.TransientModel):
    _inherit = "cash.pay.invoice"

    pos_payment_method_id = fields.Many2one(
        "pos.payment.method", string="Payment Method"
    )
    pos_session_id = fields.Many2one("pos.session")
    pos_payment_method_domain = fields.Binary(
        compute="_compute_pos_payment_method_domain"
    )

    @api.depends("pos_session_id")
    @api.depends_context("pos_pay_invoice_domain")
    def _compute_pos_payment_method_domain(self):
        for wizard in self:
            if self.env.context.get("pos_pay_invoice_domain") == "in_invoice":
                payment_methods = wizard.pos_session_id.payment_method_ids.filtered(
                    lambda pm: pm.type == "cash"
                )
            else:
                payment_methods = wizard.pos_session_id.payment_method_ids.filtered(
                    lambda pm: pm.type in ("bank", "cash")
                )
            wizard.pos_payment_method_domain = [("id", "in", payment_methods.ids)]

    @api.onchange("pos_payment_method_id")
    def _onchange_pos_payment_method_id(self):
        if self.pos_payment_method_id:
            self.journal_id = self.pos_payment_method_id.journal_id

    def _compute_invoice_domain(self):
        res = super()._compute_invoice_domain()
        # Only allow the payment of invoices of the same expected type.
        # By default, account_cash_invoice allows:
        #   - Customer: out_invoice, in_refund
        #   - Vendor: in_invoice, out_refund
        # In POS, the button context narrows it to exactly one move_type:
        #   - Customer invoice: out_invoice
        #   - Vendor bill: in_invoice
        #   - Customer refund: out_refund
        pos_pay_invoice_domain = self.env.context.get("pos_pay_invoice_domain")
        if pos_pay_invoice_domain:
            for wizard in self:
                new_domain = []
                for domain_item in wizard.invoice_domain or []:
                    if domain_item[0] == "move_type":
                        new_domain.append(("move_type", "=", pos_pay_invoice_domain))
                    else:
                        new_domain.append(domain_item)
                wizard.invoice_domain = new_domain
        return res

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if "invoice_type" in fields_list and self.env.context.get(
            "pos_pay_invoice_type"
        ):
            values["invoice_type"] = self.env.context.get("pos_pay_invoice_type")
        return values

    def _prepare_statement_line_vals(self):
        vals = super()._prepare_statement_line_vals()
        if self.pos_session_id:
            vals["pos_session_id"] = self.pos_session_id.id
        return vals

    def action_pay_invoice(self):
        self.ensure_one()
        # Vendor bills are paid through a cash statement line because POS customer
        # payment moves are built on receivable accounts.
        if not self.pos_session_id or self.invoice_id.move_type == "in_invoice":
            return super().action_pay_invoice()

        # In Odoo 19, pos.order.state no longer accepts "invoiced". Also,
        # pos.payment cannot be created if the order is already linked to an
        # account_move, so the link to the existing invoice is written after
        # creating the payment and before creating the payment move.
        pos_order = self.env["pos.order"].create(self._prepare_pos_order_vals())
        pos_order.add_payment(self._prepare_pos_payment_vals(pos_order))
        pos_order.action_pos_order_paid()
        pos_order.write({"account_move": self.invoice_id.id})

        payment_moves = pos_order._get_payments()._create_payment_moves(
            pos_order.session_id.state == "closed"
        )
        pos_order._reconcile_invoice_payments(self.invoice_id, payment_moves)
        pos_order.write({"state": "done"})

    def _prepare_pos_order_vals(self):
        return {
            "amount_total": self.amount,
            "partner_id": self.invoice_id.partner_id.id,
            "state": "draft",
            "to_invoice": False,
            "session_id": self.pos_session_id.id,
            "amount_tax": 0,
            "amount_paid": 0,
            "amount_return": 0,
        }

    def _prepare_pos_payment_vals(self, pos_order):
        return {
            "pos_order_id": pos_order.id,
            "amount": pos_order._get_rounded_amount(self.amount),
            "name": self.invoice_id.name,
            "payment_method_id": self.pos_payment_method_id.id,
        }
