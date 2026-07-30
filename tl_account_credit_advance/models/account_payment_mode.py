# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AccountPaymentMode(models.Model):
    _inherit = "account.payment.mode"

    credit_advance = fields.Boolean(
        string="Credit Advance",
        help="The remittances issued with this payment mode are not a plain "
        "direct debit: the bank advances the funds before maturity. The "
        "receivables are reclassified to the assigned receivables account and a "
        "financial debt is recognised until the customers effectively pay.",
    )
    credit_advance_line_id = fields.Many2one(
        comodel_name="credit.advance.line",
        string="Credit Advance Line",
        check_company=True,
        help="Facility used by default on the remittances of this payment mode.",
    )

    @api.constrains("credit_advance", "payment_type", "credit_advance_line_id")
    def _check_credit_advance(self):
        for mode in self:
            if not mode.credit_advance:
                continue
            if mode.payment_type != "inbound":
                raise ValidationError(
                    self.env._(
                        "The payment mode %s cannot be flagged as a credit "
                        "advance: only inbound (customer) remittances can be "
                        "financed.",
                        mode.name,
                    )
                )
            if not mode.credit_advance_line_id:
                raise ValidationError(
                    self.env._(
                        "Set the credit advance line on the payment mode %s.",
                        mode.name,
                    )
                )

    @api.onchange("credit_advance")
    def _onchange_credit_advance(self):
        """A financed remittance must be flagged as FSDD in the SEPA file."""
        if self.credit_advance:
            self.charge_financed = True
