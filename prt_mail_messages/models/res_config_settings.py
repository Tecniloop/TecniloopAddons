###################################################################################
#
#    Copyright (C) 2020 Cetmix OÜ
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU LESSER GENERAL PUBLIC LICENSE as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###################################################################################

from odoo import api, fields, models

from .common import DEFAULT_SIGNATURE_LOCATION


###################
# Config Settings #
###################
class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    messages_easy_text_preview = fields.Integer(
        string="Text preview length",
        config_parameter="cetmix.messages_easy_text_preview",
    )
    messages_easy_color_note = fields.Char(
        string="Note Background",
        config_parameter="cetmix.messages_easy_color_note",
        help="Background color for internal notes in HTML format (e.g. #fbd78b)",
    )
    messages_easy_empty_trash = fields.Integer(
        string="Empty trash in (days)",
        config_parameter="cetmix.messages_easy_empty_trash",
        default=0,
    )
    mail_incoming_smart_notify = fields.Boolean(
        string="Smart Notification",
        help="Do not notify followers "
        "if they are already notified "
        "in the incoming email",
        config_parameter="cetmix.mail_incoming_smart_notify",
        default=False,
    )
    message_signature_location = fields.Selection(
        selection=[
            ("a", "Message bottom"),
            ("b", "Before quote"),
            ("n", "No signature"),
        ],
        default=DEFAULT_SIGNATURE_LOCATION,
        string="Default Signature Location",
        help="Set default signature location",
        config_parameter="cetmix.message_signature_location",
    )
    message_quote_number = fields.Integer(
        config_parameter="cetmix.message_quote_number",
        default=0,
    )
    allow_direct_messages_to_catchall = fields.Boolean(
        config_parameter="cetmix.allow_direct_messages_to_catchall"
    )

    @api.constrains("messages_easy_text_preview")
    def _check_messages_easy_text_preview(self):
        if self.messages_easy_text_preview < 10:
            raise models.UserError(
                self.env._("Test Preview length must be greater than 10!")
            )

    @api.constrains("message_quote_number")
    def _check_message_quote_number(self):
        if self.message_quote_number < 0:
            raise models.UserError(
                self.env._("Message quote number must be greater or equal than 0!")
            )
