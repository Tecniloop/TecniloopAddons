# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, fields, models
from odoo.exceptions import UserError


class DecaDeliveryWizard(models.TransientModel):
    _name = "l10n.es.deca.delivery.wizard"
    _description = "Record DeCA Delivery"

    document_id = fields.Many2one("l10n.es.deca.document", required=True, readonly=True)
    version_id = fields.Many2one("l10n.es.deca.version", required=True, readonly=True)
    method = fields.Selection(
        [
            ("mobile", "Electronic copy on mobile device"),
            ("email", "Email"),
            ("qr", "Independent QR"),
            ("paper", "Printed copy"),
            ("other", "Other"),
        ],
        required=True,
        default="mobile",
    )
    recipient_name = fields.Char(required=True)
    note = fields.Char()

    def action_confirm(self):
        self.ensure_one()
        if self.version_id != self.document_id.current_version_id:
            raise UserError(
                _("Only delivery of the current DeCA version can be recorded.")
            )
        self.env["l10n.es.deca.delivery.log"].create(
            {
                "version_id": self.version_id.id,
                "method": self.method,
                "recipient_name": self.recipient_name,
                "note": self.note,
            }
        )
        return {"type": "ir.actions.act_window_close"}
