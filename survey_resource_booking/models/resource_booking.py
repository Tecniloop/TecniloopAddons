# Copyright 2021 Tecnativa - Jairo Llopis
# Copyright 2026 Tecnativa - Jaume Roiges Merlo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from markupsafe import Markup, escape

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.mail import email_split


class ResourceBooking(models.Model):
    _inherit = "resource.booking"

    survey_user_input_id = fields.Many2one(
        comodel_name="survey.user_input",
        string="Survey user input",
        tracking=True,
        copy=False,
        help="User responses to survey, as specified in the resource booking type.",
    )

    def _check_can_invite_survey(self):
        """Validate that the booking can produce a survey invitation."""
        for booking in self:
            if booking.state != "confirmed":
                raise UserError(
                    _(
                        "Cannot invite to fill survey because booking is not "
                        "confirmed: %s"
                    )
                    % booking.display_name
                )
            if not booking.type_id.survey_id:
                raise UserError(
                    _("This booking's type has no survey defined: %s")
                    % booking.display_name
                )
            if not booking.partner_id:
                raise UserError(
                    _("This booking has no requester: %s") % booking.display_name
                )
            if not email_split(booking.partner_id.email or ""):
                raise UserError(
                    _(
                        "Cannot send survey invitation for this booking because "
                        "the requester has no valid email: %s"
                    )
                    % booking.display_name
                )
            if booking.survey_user_input_id.state == "done":
                raise UserError(
                    _(
                        "This booking's requester has already completed the "
                        "survey: %s"
                    )
                    % booking.display_name
                )

    def _get_or_create_survey_user_input(self):
        """Return the survey answer token owned by this booking.

        The survey invitation wizard in Odoo 18 prepares answers internally from
        the recipients and may reuse the last answer found for a partner/email.
        A requester can have several bookings linked to the same survey, so the
        booking must keep and resend its own ``survey.user_input`` instead of
        letting the wizard pick an arbitrary existing answer.
        """
        self.ensure_one()
        if not self.survey_user_input_id:
            self.survey_user_input_id = self.type_id.survey_id._create_answer(
                partner=self.partner_id,
                check_attempts=False,
            )
        return self.survey_user_input_id

    def _create_survey_invite_wizard(self):
        """Create the standard survey invitation wizard for this booking.

        The wizard is used for Odoo's standard survey mail template rendering,
        but the actual mail is sent explicitly for this booking's answer token.
        """
        self.ensure_one()
        survey = self.type_id.survey_id
        action = survey.with_context(
            default_partner_ids=self.partner_id.ids,
            default_emails=self.partner_id.email,
            default_existing_mode="resend",
        ).action_send_survey()
        wizard_model = self.env[action["res_model"]].with_context(
            **action.get("context", {})
        )
        wizard_vals = wizard_model.default_get(
            [
                "survey_id",
                "template_id",
                "partner_ids",
                "emails",
                "existing_mode",
                "deadline",
                "send_email",
                "subject",
                "body",
            ]
        )
        partner_ids = wizard_vals.get("partner_ids")
        if partner_ids and all(isinstance(partner_id, int) for partner_id in partner_ids):
            wizard_vals["partner_ids"] = [(6, 0, partner_ids)]
        return wizard_model.create(wizard_vals)

    def _message_log_survey_invitation(self, mail, answer):
        """Log survey invitation traceability in the booking chatter."""
        self.ensure_one()
        survey_url = answer.get_start_url()
        body = Markup(
            _(
                "Survey invitation queued for %(partner)s for survey "
                "<b>%(survey)s</b>.<br/>"
                "Survey answer: <a href='%(url)s'>Open survey invitation</a>"
            )
        ) % {
            "partner": escape(self.partner_id.display_name),
            "survey": escape(self.type_id.survey_id.display_name),
            "url": escape(survey_url),
        }
        if mail:
            body += Markup("<br/>") + Markup(
                _("Outgoing email: %(subject)s")
            ) % {"subject": escape(mail.subject or "")}
        self.message_post(body=body, subtype_xmlid="mail.mt_note")

    def action_invite_survey(self):
        """Invite the booking requester to fill the configured survey.

        The mail is rendered by Odoo's standard ``survey.invite`` wizard, but is
        explicitly sent for ``booking.survey_user_input_id`` so the answer token
        stored on the booking is the same token received by the requester.
        """
        for booking in self:
            booking._check_can_invite_survey()
            answer = booking._get_or_create_survey_user_input()
            wizard = booking._create_survey_invite_wizard()
            mail = wizard._send_mail(answer)
            booking._message_log_survey_invitation(mail, answer)
