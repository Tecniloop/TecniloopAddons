import base64
import hashlib
from odoo import _, models, exceptions
from ..utils.pdf_signer_utils import sign_pdf_pades

class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        generated_pdf, output_type = super()._render_qweb_pdf(report_ref, res_ids, data)

        if not self.env.context.get("electronic_signature_confirmed"):
            return generated_pdf, output_type

        certificate_id = self.env.context.get("electronic_signature_certificate_id")
        pin = self.env.context.get("electronic_signature_pin")

        assignment = self.env["user.certificate.assignment"].sudo().search([
            ("user_id", "=", self.env.user.id),
            ("certificate_id", "=", certificate_id),
        ], limit=1)

        if not assignment:
            raise exceptions.AccessDenied(_("You do not have this certificate assigned."))

        assignment.validate_access(pin)

        try:
            certificate = assignment.certificate_id
            tsa_url = self.env["ir.config_parameter"].sudo().get_param(
                "l10n_firma_electronica.tsa_url",
                default="",
            )
            enable_timestamp = self.env["ir.config_parameter"].sudo().get_param(
                "l10n_firma_electronica.enable_timestamp",
                default="False",
            )
            enable_timestamp = str(enable_timestamp).strip().lower() in (
                "1", "true", "yes", "on"
            )
            signed_pdf = sign_pdf_pades(
                pdf_bytes=generated_pdf,
                pfx_bytes=certificate.action_get_pfx_bytes(),
                passphrase=certificate.master_password,
                user_name=self.env.user.name,
                tsa_url=tsa_url,
                enable_timestamp=enable_timestamp,
            )
        except Exception as error:
            raise exceptions.UserError(_("Error signing the PDF: %s") % str(error))

        report_action = False
        if isinstance(report_ref, str):
            report_action = self.env["ir.actions.report"]._get_report_from_name(report_ref)
        elif getattr(report_ref, "_name", False) == "ir.actions.report":
            report_action = report_ref

        report_label = (
            (report_action and (report_action.name or report_action.report_name))
            or (report_ref if isinstance(report_ref, str) else str(report_ref))
        )
        signed_record_ids = ",".join(str(record_id) for record_id in (res_ids or []))
        signed_model = report_action.model if report_action else False
        signed_pdf_hash = hashlib.sha256(signed_pdf).hexdigest()

        self.env["electronic.signature"].sudo().create({
            "name": _("Signed: %s") % report_label,
            "certificate_id": certificate.id,
            "user_id": self.env.user.id,
            "report_ref": report_label,
            "res_model": signed_model,
            "res_ids": signed_record_ids,
            "document_hash": signed_pdf_hash,
            "document": base64.b64encode(signed_pdf),
        })

        return signed_pdf, output_type