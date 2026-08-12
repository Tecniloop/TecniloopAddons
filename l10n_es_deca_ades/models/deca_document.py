# Copyright 2026 Ecmr DeCA contributors
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import hashlib
import io
import os

from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import signers, timestamps, validation
from pyhanko.sign.fields import SigSeedSubFilter
from pyhanko_certvalidator import ValidationContext

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class DecaDocument(models.Model):
    _inherit = "l10n.es.deca.document"

    signature_party_policy = fields.Selection(
        [
            ("shipper", "Contractual shipper"),
            ("carrier", "Effective carrier"),
            ("both", "Contractual shipper and effective carrier"),
        ],
        string="Required contractual signatures",
        default="both",
        help=(
            "Select the parties whose PAdES signatures must be embedded before the "
            "contractual DeCA version is sealed."
        ),
    )
    shipper_signing_company_id = fields.Many2one(
        "res.company",
        string="Shipper signing company",
        help=(
            "Odoo company whose active AEAT certificate signs for the contractual "
            "shipper. Its commercial partner must match the shipper."
        ),
    )
    carrier_signing_company_id = fields.Many2one(
        "res.company",
        string="Carrier signing company",
        help=(
            "Odoo company whose active AEAT certificate signs for the effective "
            "carrier. Its commercial partner must match the carrier."
        ),
    )

    @api.model
    def _company_signature_defaults(self, company):
        """Return a stable draft policy copied from the operational company.

        Defaults are copied, rather than related, so changing company settings never
        rewrites an existing draft or an issued legal record. Explicit API values and
        ``default_*`` context values always take precedence over company policy.
        """
        return {
            "purpose": company.deca_default_purpose,
            "signature_party_policy": company.deca_default_signature_party_policy,
            "shipper_signing_company_id": (
                company.deca_default_shipper_signing_company_id.id or False
            ),
            "carrier_signing_company_id": (
                company.deca_default_carrier_signing_company_id.id or False
            ),
        }

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        company_id = (
            self.env.context.get("default_company_id")
            or values.get("company_id")
            or self.env.company.id
        )
        company = self.env["res.company"].browse(company_id).exists()
        if not company:
            return values
        for field_name, value in self._company_signature_defaults(company).items():
            if (
                field_name in field_names
                and f"default_{field_name}" not in self.env.context
            ):
                values[field_name] = value
        return values

    @api.model_create_multi
    def create(self, vals_list):
        """Apply company defaults to RPC/import creation without overriding input."""
        for values in vals_list:
            company = self.env["res.company"].browse(
                values.get("company_id") or self.env.company.id
            )
            for field_name, value in self._company_signature_defaults(company).items():
                values.setdefault(field_name, value)
        return super().create(vals_list)

    @api.onchange("company_id")
    def _onchange_company_signature_defaults(self):
        """Refresh an editable draft when its operational company changes."""
        if self.company_id and self.state == "draft":
            self.update(self._company_signature_defaults(self.company_id))

    def _get_legal_fields(self):
        return super()._get_legal_fields() | {
            "signature_party_policy",
            "shipper_signing_company_id",
            "carrier_signing_company_id",
        }

    def _snapshot(self):
        values = super()._snapshot()
        values.update(
            {
                "signature_party_policy": self.signature_party_policy,
                "shipper_signing_company": self.shipper_signing_company_id.name,
                "carrier_signing_company": self.carrier_signing_company_id.name,
            }
        )
        return values

    def _required_signature_parties(self):
        """Return ordered role/company/partner tuples for deterministic signing."""
        self.ensure_one()
        parties = []
        if self.signature_party_policy in ("shipper", "both"):
            parties.append(
                (
                    "shipper",
                    self.shipper_signing_company_id,
                    self.contractual_shipper_id,
                )
            )
        if self.signature_party_policy in ("carrier", "both"):
            parties.append(
                (
                    "carrier",
                    self.carrier_signing_company_id,
                    self.effective_carrier_id,
                )
            )
        return parties

    @staticmethod
    def _signature_role_label(role):
        return _("Contractual shipper") if role == "shipper" else _("Effective carrier")

    def _validate_signature_capability(self):
        """Authorize signer use and bind every certificate to its legal party.

        ``get_certificates`` eventually returns server-side private-key paths. The
        elevated read below is therefore allowed only after role, allowed-company
        and partner-identity checks. This prevents a DeCA operator from selecting an
        unrelated company merely to make its private key sign a document.
        """
        self.ensure_one()
        if self.purpose != "contractual":
            return super()._validate_signature_capability()
        if not self.env.user.has_group(
            "l10n_es_deca_ades.group_deca_ades_signer"
        ):
            raise AccessError(
                _("Only an authorized DeCA PAdES Signer may issue this document.")
            )
        parties = self._required_signature_parties()
        if not parties:
            raise ValidationError(_("Select at least one required signature party."))
        companies = parties and self.env["res.company"].union(
            *(company for _role, company, _partner in parties)
        )
        if not companies or len(companies) != len(parties):
            raise ValidationError(
                _("Configure one distinct signing company for every required party.")
            )
        if set(companies.ids) - set(self.env.user.company_ids.ids):
            raise AccessError(
                _(
                    "You may only use certificates of companies available in your "
                    "current multi-company access."
                )
            )
        for role, company, partner in parties:
            role_label = self._signature_role_label(role)
            if not partner:
                raise ValidationError(
                    _(
                        "A contractual partner record is required for the %(role)s "
                        "signature.",
                        role=role_label,
                    )
                )
            if (
                company.partner_id.commercial_partner_id
                != partner.commercial_partner_id
            ):
                raise ValidationError(
                    _(
                        "Signing company %(company)s does not match the contractual "
                        "partner assigned to role %(role)s.",
                        company=company.display_name,
                        role=role_label,
                    )
                )
            self._get_certificate_paths(company)
        if self.company_id.deca_ades_profile == "pades_b_t" and not (
            self.company_id.deca_ades_tsa_url or ""
        ).strip():
            raise ValidationError(
                _("Configure an RFC 3161 timestamp authority URL for PAdES B-T.")
            )

    def _get_certificate_paths(self, company):
        """Resolve active OCA AEAT key material and reject stale path settings."""
        public_crt, private_key = (
            self.env["l10n.es.aeat.certificate"]
            .sudo()
            .get_certificates(company=company)
        )
        if not all(
            path and os.path.isfile(path) and os.path.getsize(path)
            for path in (public_crt, private_key)
        ):
            raise ValidationError(
                _(
                    "The active AEAT certificate files for %(company)s are not "
                    "available on this Odoo worker.",
                    company=company.display_name,
                )
            )
        return public_crt, private_key

    def _load_pdf_signer(self, company):
        public_crt, private_key = self._get_certificate_paths(company)
        try:
            signer = signers.SimpleSigner.load(private_key, public_crt)
        except Exception as error:
            raise ValidationError(
                _(
                    "The active AEAT certificate for %(company)s cannot be loaded "
                    "by the PAdES engine.",
                    company=company.display_name,
                )
            ) from error
        if signer is None:
            raise ValidationError(
                _(
                    "The active AEAT certificate for %(company)s contains no "
                    "usable signing key.",
                    company=company.display_name,
                )
            )
        return signer

    def _get_timestamper(self):
        self.ensure_one()
        if self.company_id.deca_ades_profile != "pades_b_t":
            return None
        return timestamps.HTTPTimeStamper(self.company_id.deca_ades_tsa_url.strip())

    def _postprocess_pdf(self, pdf, version):
        pdf = super()._postprocess_pdf(pdf, version)
        if self.purpose != "contractual":
            return pdf
        timestamper = self._get_timestamper()
        for role, company, _partner in self._required_signature_parties():
            signer = self._load_pdf_signer(company)
            writer = IncrementalPdfFileWriter(io.BytesIO(pdf))
            metadata = signers.PdfSignatureMetadata(
                field_name=f"DeCA_{role}_{version.version_number}",
                md_algorithm="sha256",
                subfilter=SigSeedSubFilter.PADES,
                reason=(
                    "DeCA contractual - cargador contractual"
                    if role == "shipper"
                    else "DeCA contractual - transportista efectivo"
                ),
            )
            try:
                output = signers.sign_pdf(
                    writer,
                    signature_meta=metadata,
                    signer=signer,
                    timestamper=timestamper,
                )
            except Exception as error:
                raise ValidationError(
                    _(
                        "PAdES signing failed for %(company)s. No DeCA version was "
                        "sealed.",
                        company=company.display_name,
                    )
                ) from error
            pdf = output.getvalue()
        return pdf

    def _get_postprocess_seal_values(self, pdf, version):
        if self.purpose != "contractual":
            return super()._get_postprocess_seal_values(pdf, version)
        reader = PdfFileReader(io.BytesIO(pdf))
        signatures = {
            signature.field_name: signature
            for signature in reader.embedded_signatures
        }
        expected = self._required_signature_parties()
        if len(signatures) != len(expected):
            raise ValidationError(
                _("The final PDF does not contain every required PAdES signature.")
            )
        evidence = []
        certificate_fingerprints = set()
        for role, company, _partner in expected:
            role_label = self._signature_role_label(role)
            field_name = f"DeCA_{role}_{version.version_number}"
            embedded = signatures.get(field_name)
            if not embedded:
                raise ValidationError(
                    _(
                        "The final PDF is missing the %(role)s signature.",
                        role=role_label,
                    )
                )
            # Trusting the embedded signer certificate here checks mathematical
            # integrity only. It deliberately does not claim chain, revocation,
            # qualified-certificate or legal-representation validity.
            context = ValidationContext(
                trust_roots=[embedded.signer_cert], allow_fetching=False
            )
            try:
                status = validation.validate_pdf_signature(embedded, context)
            except Exception as error:
                raise ValidationError(
                    _(
                        "The %(role)s PAdES signature cannot be validated.",
                        role=role_label,
                    )
                ) from error
            if not status.intact or not status.valid:
                raise ValidationError(
                    _(
                        "The %(role)s PAdES signature is not intact.", role=role_label
                    )
                )
            timestamp_status = getattr(status, "timestamp_validity", None)
            if self.company_id.deca_ades_profile == "pades_b_t" and (
                not timestamp_status
                or not timestamp_status.intact
                or not timestamp_status.valid
            ):
                raise ValidationError(
                    _(
                        "The %(role)s PAdES B-T signature has no valid embedded "
                        "RFC 3161 timestamp.",
                        role=role_label,
                    )
                )
            certificate = embedded.signer_cert
            certificate_fingerprint = hashlib.sha256(certificate.dump()).hexdigest()
            if certificate_fingerprint in certificate_fingerprints:
                raise ValidationError(
                    _(
                        "Distinct contractual parties cannot use the same signing "
                        "certificate."
                    )
                )
            certificate_fingerprints.add(certificate_fingerprint)
            evidence.append(
                {
                    "role": role,
                    "company_id": company.id,
                    "company_name": company.display_name,
                    "field_name": field_name,
                    "certificate_subject": certificate.subject.human_friendly,
                    "certificate_serial": str(certificate.serial_number),
                    "certificate_sha256": certificate_fingerprint,
                    "subfilter": str(embedded.sig_object.get("/SubFilter")),
                    "cryptographically_intact": bool(status.intact),
                    "cryptographically_valid": bool(status.valid),
                    "trusted_in_self_anchored_check": bool(status.trusted),
                    "timestamp_cryptographically_valid": bool(
                        timestamp_status
                        and timestamp_status.intact
                        and timestamp_status.valid
                    ),
                }
            )
        profile = (
            "PAdES B-T"
            if self.company_id.deca_ades_profile == "pades_b_t"
            else "PAdES B-B"
        )
        return {
            "signature_status": "complete",
            "signature_count": len(evidence),
            "signature_profile": profile,
            "signature_evidence": {
                "signatures": evidence,
                "invoked_by_user_id": self.env.user.id,
                "invoked_by_user_name": self.env.user.display_name,
                "timestamp_authority_url": (
                    self.company_id.deca_ades_tsa_url
                    if self.company_id.deca_ades_profile == "pades_b_t"
                    else False
                ),
                "validation_scope": (
                    "Cryptographic PDF integrity. Independent trust, revocation, "
                    "representation and AdES/QES qualification remain required."
                ),
            },
        }
