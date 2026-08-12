# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DecaVersion(models.Model):
    _name = "l10n.es.deca.version"
    _description = "Immutable DeCA PDF Version"
    _order = "document_id, version_number desc"
    _rec_name = "name"

    document_id = fields.Many2one(
        "l10n.es.deca.document",
        required=True,
        readonly=True,
        ondelete="restrict",
        index=True,
    )
    company_id = fields.Many2one(
        related="document_id.company_id", store=True, readonly=True, index=True
    )
    version_number = fields.Integer(required=True, readonly=True)
    name = fields.Char(compute="_compute_name")
    previous_version_id = fields.Many2one(
        "l10n.es.deca.version", readonly=True, ondelete="restrict"
    )
    change_reason = fields.Text(readonly=True)
    data_snapshot = fields.Json(required=True, readonly=True)
    purpose = fields.Selection(
        [
            ("administrative", "Administrative only"),
            ("contractual", "Administrative and contractual"),
        ],
        required=True,
        readonly=True,
        default="administrative",
        index=True,
    )
    signature_status = fields.Selection(
        [
            ("not_required", "Not required"),
            ("pending", "Pending"),
            ("complete", "Complete"),
        ],
        required=True,
        readonly=True,
        default="not_required",
        index=True,
    )
    signature_count = fields.Integer(readonly=True)
    signature_profile = fields.Char(readonly=True)
    signature_evidence = fields.Json(readonly=True)

    created_at = fields.Datetime(required=True, readonly=True)
    modified_at = fields.Datetime(required=True, readonly=True)
    public_until = fields.Datetime(required=True, readonly=True, index=True)
    access_token = fields.Char(required=True, readonly=True, copy=False, index=True)
    public_url = fields.Char(required=True, readonly=True)

    qr_code = fields.Binary(readonly=True, attachment=True)
    pdf_data = fields.Binary(readonly=True, attachment=True)
    pdf_filename = fields.Char(required=True, readonly=True)
    pdf_size = fields.Integer(readonly=True)
    pdf_sha256 = fields.Char(readonly=True, index=True)
    previous_chain_hash = fields.Char(readonly=True)
    chain_hash = fields.Char(readonly=True, index=True)

    delivery_log_ids = fields.One2many(
        "l10n.es.deca.delivery.log", "version_id", readonly=True
    )

    _token_unique = models.Constraint(
        "UNIQUE(access_token)", "The DeCA public access token must be unique."
    )
    _document_version_unique = models.Constraint(
        "UNIQUE(document_id, version_number)",
        "A DeCA version number can only occur once per document.",
    )

    def _compute_name(self):
        for record in self:
            record.name = f"{record.document_id.name} / v{record.version_number}"

    @api.model_create_multi
    def create(self, vals_list):
        """Allow version creation only from the serialized sealing workflow.

        ACLs are not the only boundary: this guard also protects installations that
        later grant broader model access.  A forged RPC context is insufficient
        because the call must run in a superuser environment as well.
        """
        if not self.env.su or not self.env.context.get("_deca_create_version"):
            raise UserError(
                _("DeCA versions can only be created by the sealing workflow.")
            )
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su or not self.env.context.get("_deca_seal_version"):
            raise UserError(_("A sealed DeCA version is immutable."))
        allowed = {
            "qr_code",
            "pdf_data",
            "pdf_size",
            "pdf_sha256",
            "chain_hash",
            "signature_status",
            "signature_count",
            "signature_profile",
            "signature_evidence",
        }
        if set(vals) - allowed:
            raise UserError(_("Only technical sealing fields may be written once."))
        for record in self:
            if record.pdf_data:
                raise UserError(_("A sealed DeCA PDF cannot be replaced."))
        return super().write(vals)

    def unlink(self):
        raise UserError(
            _("DeCA versions form the legal audit trail and cannot be deleted.")
        )

    def action_download(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": self.public_url, "target": "new"}

    def get_pdf_bytes(self):
        self.ensure_one()
        return base64.b64decode(self.pdf_data or b"")
