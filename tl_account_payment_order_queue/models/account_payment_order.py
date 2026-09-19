# Copyright 2026 Tecniloop
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models


class AccountPaymentOrder(models.Model):
    _inherit = "account.payment.order"

    upload_job_state = fields.Selection(
        selection=[
            ("idle", "Idle"),
            ("queued", "Queued"),
            ("posting", "Posting Payments"),
            ("grouping", "Generating Grouped Moves"),
            ("done", "Done"),
            ("failed", "Failed"),
        ],
        default="idle",
        copy=False,
        tracking=True,
        help="Background processing status after File Uploaded.",
    )
    upload_job_error = fields.Text(copy=False, readonly=True)

    def _use_queue_for_upload(self):
        self.ensure_one()
        if self.env.context.get("skip_queue_job"):
            return False
        mode = self.payment_mode_id
        return bool(mode and mode.upload_use_queue_job)

    def generated2uploaded(self):
        """Enqueue posting when the mode asks for queue_job.

        Small remittances can still run inline. Large ones (thousands of
        lines) must not run inside the HTTP request: posting N
        account.payment plus a grouped move of N+1 lines collapses the
        worker (memory, lock time, HTTP timeout).
        """
        queued = self.env["account.payment.order"]
        inline = self.env["account.payment.order"]
        for order in self:
            if order._use_queue_for_upload():
                queued |= order
            else:
                inline |= order
        res = True
        if inline:
            res = super(AccountPaymentOrder, inline).generated2uploaded()
            inline.write({"upload_job_state": "done", "upload_job_error": False})
        for order in queued:
            order.write(
                {
                    "upload_job_state": "queued",
                    "upload_job_error": False,
                    "date_uploaded": fields.Date.context_today(order),
                    "state": "uploaded",
                }
            )
            order.with_delay(
                channel="root.payment_order",
                description=self.env._(
                    "Post remittance %(name)s (batch)",
                    name=order.name,
                ),
                identity_key=f"tl_po_upload_{order.id}",
            )._job_post_and_reconcile_batch()
        return res

    def _pending_upload_payments(self):
        self.ensure_one()
        return self.payment_ids.filtered(lambda p: p.state != "posted")

    def _job_post_and_reconcile_batch(self):
        """Post and reconcile one batch of payments, then chain the next job."""
        self.ensure_one()
        self.upload_job_state = "posting"
        try:
            pending = self._pending_upload_payments()
            if pending:
                batch_size = self.payment_mode_id._get_upload_queue_batch_size()
                batch = pending[:batch_size]
                self._post_and_reconcile_payments(batch)
                leftover = self._pending_upload_payments()
                if leftover:
                    self.with_delay(
                        channel="root.payment_order",
                        description=self.env._(
                            "Post remittance %(name)s (remaining %(n)s)",
                            name=self.name,
                            n=len(leftover),
                        ),
                        identity_key=f"tl_po_upload_{self.id}",
                    )._job_post_and_reconcile_batch()
                    return True
            self._enqueue_or_run_grouped_moves()
        except Exception as exc:
            self.write(
                {
                    "upload_job_state": "failed",
                    "upload_job_error": str(exc),
                }
            )
            raise
        return True

    def _post_and_reconcile_payments(self, payments):
        """Same contract as account.payment.order.post_and_reconcile, one batch."""
        if not payments:
            return
        payments.action_post()
        for payment in payments:
            (
                payment.payment_line_ids.move_line_id
                + payment.move_id.line_ids.filtered(
                    lambda x, p=payment: x.account_id == p.destination_account_id
                )
            ).reconcile()

    def _enqueue_or_run_grouped_moves(self):
        self.ensure_one()
        generate = (
            hasattr(self, "generate_move")
            and self.payment_mode_id.generate_move
            and len(self.payment_ids) > 1
        )
        if not generate:
            self.write({"upload_job_state": "done", "upload_job_error": False})
            return True
        self.write({"upload_job_state": "grouping"})
        self.with_delay(
            channel="root.payment_order",
            description=self.env._(
                "Grouped moves for remittance %s", self.name
            ),
            identity_key=f"tl_po_group_{self.id}",
        )._job_generate_grouped_moves()
        return True

    def generate_move(self):
        """Split huge same-date groups to keep move size bounded.

        Only runs when ``account_payment_order_grouped_output`` is installed
        (it provides ``_prepare_trf_moves`` / ``_create_reconcile_move``).
        """
        if not hasattr(self, "_prepare_trf_moves") or not hasattr(
            self, "_create_reconcile_move"
        ):
            return True
        self.ensure_one()
        if self.env.context.get("skip_grouped_split"):
            return super().generate_move()
        trfmoves = self._prepare_trf_moves()
        batch_size = self.payment_mode_id._get_grouped_move_batch_size()
        for hashcode, payments in trfmoves.items():
            for index, start in enumerate(range(0, len(payments), batch_size)):
                chunk = payments[start : start + batch_size]
                chunk_hash = f"{hashcode}-{index}"
                self._create_reconcile_move(chunk_hash, chunk)
        return True

    def _job_generate_grouped_moves(self):
        self.ensure_one()
        try:
            if hasattr(self, "generate_move"):
                self.generate_move()
            self.write({"upload_job_state": "done", "upload_job_error": False})
        except Exception as exc:
            self.write(
                {
                    "upload_job_state": "failed",
                    "upload_job_error": str(exc),
                }
            )
            raise
        return True

    @api.model
    def _job_store_done_message(self):
        return True
