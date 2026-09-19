# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class AccountPaymentMode(models.Model):
    _inherit = "account.payment.mode"

    upload_use_queue_job = fields.Boolean(
        string="Process File Upload With Queue Job",
        default=True,
        help="When the bank file is marked as uploaded, post and reconcile "
        "payments in background jobs. Recommended for large remittances.",
    )
    upload_queue_batch_size = fields.Integer(
        string="Upload Job Batch Size",
        default=100,
        help="Number of account.payment records posted and reconciled "
        "per queue job. Keep it low (50-200) for remittances of thousands "
        "of lines.",
    )
    grouped_move_batch_size = fields.Integer(
        string="Grouped Move Batch Size",
        default=200,
        help="Maximum payments packed into a single grouped journal entry "
        "(account_payment_order_grouped_output). Avoids one 5000-line move.",
    )

    def _get_upload_queue_batch_size(self):
        self.ensure_one()
        return max(1, self.upload_queue_batch_size or 100)

    def _get_grouped_move_batch_size(self):
        self.ensure_one()
        return max(1, self.grouped_move_batch_size or 200)
