# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import hashlib
import io
import re
import secrets
from datetime import timedelta
from urllib.parse import urljoin, urlparse

import qrcode

# Odoo 19 pins PyPDF2 on Python <= 3.12 and PyPDF on Python >= 3.13.
try:
    from pypdf import PdfReader, PdfWriter
except ImportError:  # pragma: no cover - selected by the Odoo Python runtime
    from PyPDF2 import PdfReader, PdfWriter

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


MAX_PDF_BYTES = 5 * 1024 * 1024


class DecaDocument(models.Model):
    _name = "l10n.es.deca.document"
    _description = "Spanish Electronic Transport Control Document (DeCA)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "transport_date desc, id desc"

    name = fields.Char(
        required=True,
        readonly=True,
        copy=False,
        default="/",
        tracking=True,
        index=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("issued", "Issued"),
            ("in_transit", "In transit"),
            ("done", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        readonly=True,
        default="draft",
        copy=False,
        tracking=True,
        index=True,
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    responsible_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, tracking=True
    )
    purpose = fields.Selection(
        [
            ("administrative", "Administrative only"),
            ("contractual", "Administrative and contractual"),
        ],
        string="Document purpose",
        required=True,
        default="administrative",
        tracking=True,
        help=(
            "Contractual use requires an optional signing addon and at least "
            "advanced electronic signatures whenever signatures are included."
        ),
    )

    # The DeCA is legally scoped per transport service.  A batch is retained as
    # operational grouping evidence, but each document always points to one picking.
    picking_id = fields.Many2one(
        "stock.picking",
        string="Transfer",
        copy=False,
        check_company=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    batch_id = fields.Many2one(
        "stock.picking.batch",
        string="Batch transfer",
        copy=False,
        check_company=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )

    contractual_shipper_id = fields.Many2one(
        "res.partner", string="Contractual shipper"
    )
    contractual_shipper_name = fields.Char()
    contractual_shipper_vat = fields.Char(
        string="Contractual shipper Tax ID"
    )
    contractual_shipper_address = fields.Text()
    effective_carrier_id = fields.Many2one("res.partner", string="Effective carrier")
    effective_carrier_name = fields.Char()
    effective_carrier_vat = fields.Char(string="Effective carrier Tax ID")

    origin = fields.Char()
    destination = fields.Char()
    goods_nature = fields.Text()
    goods_weight = fields.Float(string="Goods weight")
    weight_uom = fields.Char(string="Weight unit", default="kg")
    alternative_weight_measure = fields.Char(
        help="Alternative magnitude when exact weight is difficult to determine."
    )
    special_permit_required = fields.Boolean()
    special_permit_ref = fields.Char(string="Special traffic permit")
    transport_date = fields.Date(
        required=True, default=fields.Date.context_today, index=True
    )
    tractor_plate = fields.Char()
    trailer_plate = fields.Char()
    observations = fields.Text()

    driver_id = fields.Many2one("res.partner")
    driver_name = fields.Char()
    planned_start_at = fields.Datetime()
    actual_start_at = fields.Datetime(readonly=True, copy=False)
    actual_end_at = fields.Datetime(readonly=True, copy=False)

    version_ids = fields.One2many(
        "l10n.es.deca.version", "document_id", readonly=True, copy=False
    )
    current_version_id = fields.Many2one(
        "l10n.es.deca.version", readonly=True, copy=False, ondelete="restrict"
    )
    version_count = fields.Integer(compute="_compute_version_count")
    current_pdf_url = fields.Char(
        related="current_version_id.public_url", readonly=True
    )
    delivery_log_ids = fields.One2many(
        "l10n.es.deca.delivery.log", "document_id", readonly=True
    )

    _LEGAL_FIELDS = {
        "company_id",
        "purpose",
        "picking_id",
        "batch_id",
        "contractual_shipper_id",
        "contractual_shipper_name",
        "contractual_shipper_vat",
        "contractual_shipper_address",
        "effective_carrier_id",
        "effective_carrier_name",
        "effective_carrier_vat",
        "origin",
        "destination",
        "goods_nature",
        "goods_weight",
        "weight_uom",
        "alternative_weight_measure",
        "special_permit_required",
        "special_permit_ref",
        "transport_date",
        "tractor_plate",
        "trailer_plate",
        "observations",
        "driver_id",
        "driver_name",
        "planned_start_at",
    }
    _SYSTEM_FIELDS = {
        "state",
        "actual_start_at",
        "actual_end_at",
        "current_version_id",
    }
    _company_reference_unique = models.Constraint(
        "UNIQUE(company_id, name)", "The DeCA reference must be unique per company."
    )
    _picking_unique = models.Constraint(
        "UNIQUE(picking_id)",
        "Only one DeCA document can be linked to a stock transfer.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            internal_create = self.env.su and self.env.context.get(
                "_deca_internal_create"
            )
            if not internal_create:
                vals["name"] = "/"
                vals["state"] = "draft"
                vals.pop("actual_start_at", None)
                vals.pop("actual_end_at", None)
                vals.pop("current_version_id", None)
            if vals.get("name", "/") == "/":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("l10n.es.deca.document")
                    or "/"
                )
        return super().create(vals_list)

    def write(self, vals):
        internal_write = self.env.su and self.env.context.get("_deca_internal_write")
        revision_write = self.env.su and self.env.context.get(
            "_deca_revision_write"
        )
        if set(vals) & self._SYSTEM_FIELDS and not internal_write:
            raise UserError(
                _("Use the DeCA workflow actions to change its legal state.")
            )
        if set(vals) & self._get_legal_fields() and not revision_write:
            locked = self.filtered(lambda record: record.state != "draft")
            if locked:
                raise UserError(
                    _(
                        "Issued DeCA data cannot be edited directly. Create a traced "
                        "revision."
                    )
                )
        return super().write(vals)

    def _get_legal_fields(self):
        """Return fields whose issued values may only change through a revision.

        Optional integration addons extend this method instead of replacing the
        private class constant. This keeps revision wizards and the immutability
        guard aligned when a downstream module adds contractual signing policy.
        """
        return self._LEGAL_FIELDS

    def unlink(self):
        if any(record.state != "draft" or record.version_ids for record in self):
            raise UserError(
                _("Only a draft DeCA without issued versions can be deleted.")
            )
        return super().unlink()

    @api.onchange("contractual_shipper_id")
    def _onchange_contractual_shipper_id(self):
        partner = self.contractual_shipper_id
        if partner:
            self.contractual_shipper_name = (
                partner.commercial_company_name or partner.name
            )
            self.contractual_shipper_vat = partner.vat
            self.contractual_shipper_address = partner._display_address(
                without_company=True
            )

    @api.onchange("effective_carrier_id")
    def _onchange_effective_carrier_id(self):
        partner = self.effective_carrier_id
        if partner:
            self.effective_carrier_name = (
                partner.commercial_company_name or partner.name
            )
            self.effective_carrier_vat = partner.vat

    @api.onchange("driver_id")
    def _onchange_driver_id(self):
        if self.driver_id:
            self.driver_name = self.driver_id.name

    @api.onchange("tractor_plate", "trailer_plate")
    def _onchange_plates(self):
        if self.tractor_plate:
            self.tractor_plate = self.tractor_plate.strip().upper()
        if self.trailer_plate:
            self.trailer_plate = self.trailer_plate.strip().upper()

    @api.constrains("goods_weight")
    def _check_nonnegative_weight(self):
        for record in self:
            if record.goods_weight < 0:
                raise ValidationError(_("Goods weight cannot be negative."))

    @api.constrains("picking_id", "batch_id", "company_id")
    def _check_stock_source(self):
        """Keep draft stock links company-consistent and structurally unambiguous."""
        for record in self:
            if record.picking_id and record.picking_id.company_id != record.company_id:
                raise ValidationError(
                    _("The transfer and DeCA must belong to the same company.")
                )
            if record.batch_id and record.batch_id.company_id != record.company_id:
                raise ValidationError(
                    _("The batch transfer and DeCA must belong to the same company.")
                )
            if (
                record.state == "draft"
                and record.batch_id
                and record.picking_id
                and record.picking_id.batch_id != record.batch_id
            ):
                raise ValidationError(
                    _("The selected transfer does not belong to the selected batch.")
                )

    @api.constrains("current_version_id")
    def _check_current_version(self):
        for record in self:
            if (
                record.current_version_id
                and record.current_version_id.document_id != record
            ):
                raise ValidationError(
                    _("The current DeCA version must belong to the same document.")
                )

    def _compute_version_count(self):
        for record in self:
            record.version_count = len(record.version_ids)

    def _lock_for_workflow(self):
        """Serialize legal state and version transitions on the database row.

        A row-level lock closes the gap between checking the current version and
        writing its successor.  Without it, two workers could both seal version N+1
        or start transport with an already superseded version.
        """
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM l10n_es_deca_document WHERE id = %s FOR UPDATE", [self.id]
        )
        self.invalidate_recordset(
            [
                "state",
                "actual_start_at",
                "actual_end_at",
                "version_ids",
                "current_version_id",
            ]
        )

    def _validate_for_issue(self):
        """Enforce Order FOM/2861/2012 article 6 before PDF generation."""
        self.ensure_one()
        if not self.picking_id:
            raise ValidationError(_("A DeCA must be linked to a stock transfer."))
        if not self.current_version_id and self.picking_id.state in (
            "done",
            "cancel",
        ):
            raise ValidationError(
                _("A DeCA cannot be first issued for a done or cancelled transfer.")
            )
        if (
            not self.current_version_id
            and self.batch_id
            and self.picking_id.batch_id != self.batch_id
        ):
            raise ValidationError(
                _(
                    "The transfer no longer belongs to the recorded batch. Update the "
                    "draft stock links before issuing the DeCA."
                )
            )
        required_values = {
            _("contractual shipper name"): self.contractual_shipper_name,
            _("contractual shipper Tax ID"): self.contractual_shipper_vat,
            _("contractual shipper address"): self.contractual_shipper_address,
            _("effective carrier name"): self.effective_carrier_name,
            _("effective carrier Tax ID"): self.effective_carrier_vat,
            _("origin"): self.origin,
            _("destination"): self.destination,
            _("goods nature"): self.goods_nature,
            _("transport date"): self.transport_date,
            _("tractor plate"): self.tractor_plate,
        }
        missing = [
            label
            for label, value in required_values.items()
            if value is None
            or value is False
            or (isinstance(value, str) and not value.strip())
        ]
        if missing:
            raise ValidationError(
                _(
                    "Missing essential DeCA data: %(fields)s",
                    fields=", ".join(missing),
                )
            )
        if (
            not self.goods_weight
            and not (self.alternative_weight_measure or "").strip()
        ):
            raise ValidationError(
                _(
                    "Enter the goods weight or an alternative magnitude when exact "
                    "weight cannot be determined."
                )
            )
        if self.special_permit_required and not (self.special_permit_ref or "").strip():
            raise ValidationError(
                _("Enter the required special traffic permit reference.")
            )
        if self.actual_start_at and not self.current_version_id:
            raise ValidationError(
                _("A first DeCA cannot be issued after transport has started.")
            )
        self._validate_signature_capability()

    def _validate_signature_capability(self):
        """Fail closed for contractual use when no signing addon is installed.

        The base addon intentionally cannot claim that an unsigned document is a
        completed contractual instrument. A signing addon must override this hook,
        validate its party policy and cryptographically process the final PDF.
        """
        self.ensure_one()
        if self.purpose == "contractual":
            raise ValidationError(
                _(
                    "Contractual use requires an installed and configured "
                    "electronic-signature addon. Administrative DeCA issuance "
                    "remains available without signatures."
                )
            )

    def _get_public_base_url(self):
        """Read the deployment URL with elevation, never business record data."""
        base_url = self.env["ir.config_parameter"].sudo().get_param(
            "l10n_es_deca.public_base_url"
        ) or self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        base_url = (base_url or "").strip().rstrip("/")
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValidationError(
                _(
                    "Configure a clean HTTPS URL in l10n_es_deca.public_base_url "
                    "(TLS 1.2 or newer; no credentials, query or fragment)."
                )
            )
        return base_url

    def _snapshot(self):
        """Freeze legal values and stock provenance used by the sealed PDF."""
        self.ensure_one()
        return {
            "reference": self.name,
            "purpose": self.purpose,
            "picking_reference": self.picking_id.name,
            "batch_reference": self.batch_id.name,
            "contractual_shipper_name": self.contractual_shipper_name,
            "contractual_shipper_vat": self.contractual_shipper_vat,
            "contractual_shipper_address": self.contractual_shipper_address,
            "effective_carrier_name": self.effective_carrier_name,
            "effective_carrier_vat": self.effective_carrier_vat,
            "origin": self.origin,
            "destination": self.destination,
            "goods_nature": self.goods_nature,
            "goods_weight": self.goods_weight,
            "weight_uom": self.weight_uom,
            "alternative_weight_measure": self.alternative_weight_measure,
            "special_permit_required": self.special_permit_required,
            "special_permit_ref": self.special_permit_ref,
            "transport_date": fields.Date.to_string(self.transport_date),
            "tractor_plate": self.tractor_plate,
            "trailer_plate": self.trailer_plate,
            "observations": self.observations,
            "driver_name": self.driver_name,
            "planned_start_at": fields.Datetime.to_string(self.planned_start_at),
        }

    @staticmethod
    def _make_qr_png(url):
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        output = io.BytesIO()
        qr.make_image(fill_color="black", back_color="white").save(output, format="PNG")
        return output.getvalue()

    @staticmethod
    def _set_pdf_metadata(pdf, title, created_at, modified_at):
        """Write the timestamps required by section two of the 2026 Resolution."""
        reader = PdfReader(io.BytesIO(pdf))
        writer = PdfWriter()
        writer.append_pages_from_reader(reader)
        metadata = {
            str(key): str(value)
            for key, value in (reader.metadata or {}).items()
            if key and value is not None
        }
        metadata.update(
            {
                "/Title": title,
                "/Subject": "Documento electrónico de control administrativo (DeCA)",
                "/Creator": "Odoo 19 - l10n_es_deca",
                "/CreationDate": fields.Datetime.to_datetime(created_at).strftime(
                    "D:%Y%m%d%H%M%SZ"
                ),
                "/ModDate": fields.Datetime.to_datetime(modified_at).strftime(
                    "D:%Y%m%d%H%M%SZ"
                ),
            }
        )
        writer.add_metadata(metadata)
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    def _postprocess_pdf(self, pdf, version):
        """Extension hook for an optional PDF signature or organisational seal.

        The administrative DeCA does not need a signature to be valid.  A glue
        addon may override this hook to add a PAdES signature before the final
        size, SHA-256 and hash-chain seals are calculated.  Keeping that addon
        separate avoids forcing Inventory users to install Accounting/AEAT.

        An override must return the complete final PDF bytes and must not write
        on ``version``: it is still an unsealed draft at this point.
        """
        self.ensure_one()
        return pdf

    def _get_postprocess_seal_values(self, pdf, version):
        """Return immutable evidence produced by an optional PDF processor.

        The base flow calls this only after ``_postprocess_pdf`` returns the final
        bytes and before the version is sealed. Signature addons use it to parse
        and validate their output without mutating the not-yet-sealed version.
        """
        self.ensure_one()
        return {
            "signature_status": "not_required",
            "signature_count": 0,
            "signature_profile": False,
            "signature_evidence": False,
        }

    def _create_version(self, change_reason=None):
        """Seal a native PDF/QR version without replacing any previous version.

        Implements the 5 June 2026 Resolution controls for native PDF, embedded
        QR, direct unique URL and traced changes.  The method is transactionally
        serialized by ``_lock_for_workflow`` and all elevated writes are narrowed
        by private context flags checked by the target models.
        """
        self.ensure_one()
        self._lock_for_workflow()
        if change_reason is None:
            if self.state != "draft" or self.version_ids:
                raise UserError(_("This DeCA has already been issued."))
        elif self.state not in ("issued", "in_transit") or not self.current_version_id:
            raise UserError(_("A revision requires a current issued DeCA."))
        self._validate_for_issue()
        previous = self.current_version_id
        number = max(self.version_ids.mapped("version_number"), default=0) + 1
        now = fields.Datetime.now()
        token = secrets.token_urlsafe(32)
        public_url = urljoin(self._get_public_base_url() + "/", f"deca/pdf/{token}")
        public_until = now + timedelta(days=366)
        safe_reference = re.sub(r"[^A-Za-z0-9._-]+", "-", self.name).strip("-.")
        filename = f"{safe_reference or 'DeCA'}-v{number}.pdf"
        values = {
            "document_id": self.id,
            "version_number": number,
            "previous_version_id": previous.id,
            "change_reason": change_reason,
            "data_snapshot": self._snapshot(),
            "created_at": now,
            "modified_at": now,
            "public_until": public_until,
            "access_token": token,
            "public_url": public_url,
            "purpose": self.purpose,
            "signature_status": (
                "pending" if self.purpose == "contractual" else "not_required"
            ),
            "qr_code": base64.b64encode(self._make_qr_png(public_url)),
            "pdf_filename": filename,
            "previous_chain_hash": previous.chain_hash,
        }
        version = (
            self.env["l10n.es.deca.version"]
            .sudo()
            .with_context(_deca_create_version=True)
            .create(values)
        )
        # The statutory PDF is canonical Spanish regardless of the operator's UI.
        pdf, _content_type = (
            self.env["ir.actions.report"]
            .sudo()
            .with_context(lang="es_ES")
            ._render_qweb_pdf("l10n_es_deca.action_report_deca", res_ids=version.ids)
        )
        pdf = self._set_pdf_metadata(pdf, version.name, now, now)
        pdf = self._postprocess_pdf(pdf, version)
        if not isinstance(pdf, bytes) or not pdf.startswith(b"%PDF"):
            raise ValidationError(
                _("The DeCA PDF post-processing hook returned an invalid PDF.")
            )
        if len(pdf) > MAX_PDF_BYTES:
            raise ValidationError(
                _("The generated DeCA PDF exceeds the legal 5 MB limit.")
            )
        pdf_hash = hashlib.sha256(pdf).hexdigest()
        chain_hash = hashlib.sha256(
            f"{previous.chain_hash or ''}:{pdf_hash}".encode()
        ).hexdigest()
        postprocess_values = self._get_postprocess_seal_values(pdf, version)
        if self.purpose == "contractual" and (
            postprocess_values.get("signature_status") != "complete"
            or not postprocess_values.get("signature_count")
        ):
            raise ValidationError(
                _(
                    "The contractual DeCA did not produce the required "
                    "electronic-signature evidence."
                )
            )
        version.sudo().with_context(_deca_seal_version=True).write(
            {
                "pdf_data": base64.b64encode(pdf),
                "pdf_size": len(pdf),
                "pdf_sha256": pdf_hash,
                "chain_hash": chain_hash,
                **postprocess_values,
            }
        )
        next_state = self.state if self.state == "in_transit" else "issued"
        self.sudo().with_context(_deca_internal_write=True).write(
            {"current_version_id": version.id, "state": next_state}
        )
        self.message_post(
            body=_(
                "DeCA version %(version)s sealed (SHA-256: %(hash)s).",
                version=number,
                hash=pdf_hash,
            ),
            subtype_xmlid="mail.mt_note",
        )
        return version

    def action_issue(self):
        self.ensure_one()
        self.check_access_rights("write")
        self.check_access_rule("write")
        if self.state != "draft" or self.version_ids:
            raise UserError(
                _("Only a new draft DeCA can be issued with this action.")
            )
        version = self._create_version()
        return version.action_download()

    def _apply_revision(self, values, reason, expected_version=None):
        self.ensure_one()
        self.check_access_rights("write")
        self.check_access_rule("write")
        self._lock_for_workflow()
        if self.state not in ("issued", "in_transit"):
            raise UserError(_("Only an issued or in-transit DeCA can be revised."))
        if expected_version and self.current_version_id != expected_version:
            raise UserError(
                _(
                    "A newer DeCA version was issued while this form was open. "
                    "Close it and create the revision again from the current version."
                )
            )
        if not (reason or "").strip():
            raise ValidationError(_("A revision reason is mandatory."))
        self.sudo().with_context(_deca_revision_write=True).write(values)
        return self._create_version(change_reason=reason.strip())

    def action_start_transport(self):
        self.ensure_one()
        self.check_access_rights("write")
        self.check_access_rule("write")
        self._lock_for_workflow()
        if self.state != "issued" or not self.current_version_id:
            raise UserError(_("Issue the DeCA before starting transport."))
        if not self.current_version_id.delivery_log_ids:
            raise UserError(
                _("Record delivery of the current PDF/QR to the driver first.")
            )
        now = fields.Datetime.now()
        if self.current_version_id.created_at > now:
            raise UserError(_("The DeCA creation timestamp is invalid."))
        self.sudo().with_context(_deca_internal_write=True).write(
            {"state": "in_transit", "actual_start_at": now}
        )
        return True

    def action_complete_transport(self):
        self.ensure_one()
        self.check_access_rights("write")
        self.check_access_rule("write")
        self._lock_for_workflow()
        if self.state != "in_transit":
            raise UserError(_("Only an in-transit DeCA can be completed."))
        if not self.current_version_id.delivery_log_ids:
            raise UserError(
                _("Deliver the current revised PDF/QR to the driver first.")
            )
        self.sudo().with_context(_deca_internal_write=True).write(
            {"state": "done", "actual_end_at": fields.Datetime.now()}
        )
        return True

    def action_cancel(self):
        self.ensure_one()
        self.check_access_rights("write")
        self.check_access_rule("write")
        self._lock_for_workflow()
        if self.state != "draft":
            raise UserError(_("An issued DeCA cannot be cancelled or removed."))
        self.sudo().with_context(_deca_internal_write=True).write(
            {"state": "cancelled"}
        )
        return True

    def action_reset_to_draft(self):
        """Reopen an unissued cancelled document without touching audit evidence."""
        self.ensure_one()
        self.check_access_rights("write")
        self.check_access_rule("write")
        self._lock_for_workflow()
        if self.state != "cancelled" or self.version_ids:
            raise UserError(
                _("Only a cancelled DeCA without issued versions can be reopened.")
            )
        self.sudo().with_context(_deca_internal_write=True).write(
            {"state": "draft"}
        )
        return True

    def action_download_current(self):
        self.ensure_one()
        self.check_access_rights("read")
        self.check_access_rule("read")
        if not self.current_version_id:
            raise UserError(_("There is no issued PDF yet."))
        return self.current_version_id.action_download()

    def action_open_revision_wizard(self):
        self.ensure_one()
        self.check_access_rights("write")
        self.check_access_rule("write")
        return {
            "type": "ir.actions.act_window",
            "name": _("Create traced DeCA revision"),
            "res_model": "l10n.es.deca.revision.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_document_id": self.id},
        }

    def action_open_delivery_wizard(self):
        self.ensure_one()
        self.check_access_rights("write")
        self.check_access_rule("write")
        if not self.current_version_id:
            raise UserError(_("Issue a DeCA PDF first."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Record delivery to driver"),
            "res_model": "l10n.es.deca.delivery.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_document_id": self.id,
                "default_version_id": self.current_version_id.id,
                "default_recipient_name": self.driver_name,
            },
        }
