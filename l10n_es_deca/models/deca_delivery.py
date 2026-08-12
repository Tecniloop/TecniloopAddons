# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DecaDeliveryLog(models.Model):
    _name = "l10n.es.deca.delivery.log"
    _description = "DeCA Delivery Evidence"
    _order = "delivered_at desc, id desc"

    version_id = fields.Many2one(
        "l10n.es.deca.version",
        required=True,
        readonly=True,
        ondelete="restrict",
        index=True,
    )
    document_id = fields.Many2one(
        related="version_id.document_id", store=True, readonly=True, index=True
    )
    company_id = fields.Many2one(
        related="document_id.company_id", store=True, readonly=True, index=True
    )
    delivered_at = fields.Datetime(
        required=True, readonly=True, default=fields.Datetime.now
    )
    method = fields.Selection(
        [
            ("mobile", "Electronic copy on mobile device"),
            ("email", "Email"),
            ("qr", "Independent QR"),
            ("paper", "Printed copy"),
            ("other", "Other"),
        ],
        required=True,
        readonly=True,
    )
    recipient_name = fields.Char(required=True, readonly=True)
    note = fields.Char(readonly=True)
    delivered_by_id = fields.Many2one(
        "res.users", required=True, readonly=True, default=lambda self: self.env.user
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals["delivered_at"] = fields.Datetime.now()
            vals["delivered_by_id"] = self.env.user.id
            vals["recipient_name"] = (vals.get("recipient_name") or "").strip()
            if not vals["recipient_name"]:
                raise UserError(_("The delivery recipient is required."))
            version = self.env["l10n.es.deca.version"].browse(vals.get("version_id"))
            if not version.exists() or not version.pdf_data:
                raise UserError(
                    _("Delivery can only be recorded for a sealed DeCA PDF.")
                )
            version.document_id._lock_for_workflow()
            if version.document_id.state not in ("issued", "in_transit"):
                raise UserError(_("The DeCA must be issued or in transit."))
            if version != version.document_id.current_version_id:
                raise UserError(
                    _("Only delivery of the current DeCA version can be recorded.")
                )
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(
            _("DeCA delivery evidence is append-only and cannot be changed.")
        )

    def unlink(self):
        raise UserError(_("DeCA delivery evidence cannot be deleted."))
