# Copyright 2021 Tecnativa - Jairo Llopis
# Copyright 2026 Tecnativa - Jaume Roigés Merlo
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

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

    def _create_survey_invite_wizard(self):
        """Create the standard survey invitation wizard for this booking.

        Odoo 18 still exposes ``survey.user_input.action_resend()``, but relying on
        ``odoo.tests.common.Form`` from production code is unnecessary. Building
        the transient record from the action context keeps the same defaults as
        the UI wizard, including template, recipients and resend mode.
        """
        self.ensure_one()
        action = self.survey_user_input_id.action_resend()
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
            ]
        )
        partner_ids = wizard_vals.get("partner_ids")
        if partner_ids and all(
            isinstance(partner_id, int) for partner_id in partner_ids
        ):
            wizard_vals["partner_ids"] = [(6, 0, partner_ids)]
        return wizard_model.create(wizard_vals)

    def action_invite_survey(self):
        """Invite requester to fill survey, if needed and possible."""
        for one in self:
            # Skip unconfirmed bookings, or finished user inputs
            if one.state != "confirmed":
                raise UserError(
                    _("Cannot invite to fill survey because booking not confirmed: %s")
                    % one.display_name
                )
            if one.survey_user_input_id.state == "done":
                raise UserError(
                    _(
                        "This booking's requester was already invited "
                        "to fill survey: %s"
                    )
                    % one.display_name
                )
            if not one.survey_user_input_id:
                if not one.type_id.survey_id:
                    raise UserError(
                        _("This booking's type has no survey defined: %s")
                        % one.display_name
                    )
                if not email_split(one.partner_id.email):
                    raise UserError(
                        _(
                            "Cannot send survey invitation for this booking "
                            "because the requester has no email: %s"
                        )
                        % one.display_name
                    )
                one.survey_user_input_id = one.type_id.survey_id._create_answer(
                    partner=one.partner_id,
                    check_attempts=False,
                )
            # Enqueue survey invitation
            wizard = one._create_survey_invite_wizard()
            wizard.action_invite()
