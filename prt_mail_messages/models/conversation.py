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
from odoo.tools.mail import email_split_and_format, parse_contact_from_email

from .tools import _prepare_date_display


################
# Conversation #
################
class Conversation(models.Model):
    _name = "cetmix.conversation"
    _description = "Conversation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "last_message_post desc, id desc"

    def _default_participants(self):
        """
        User is a participant by default.
        Override in case any custom logic is needed
        """
        return [(4, self.env.user.partner_id.id)]

    active = fields.Boolean(default=True)
    name = fields.Char(string="Subject", required=True, tracking=True)
    author_id = fields.Many2one(
        comodel_name="res.partner",
        ondelete="set null",
        default=lambda self: self.env.user.partner_id.id,
    )
    partner_ids = fields.Many2many(
        string="Participants", comodel_name="res.partner", default=_default_participants
    )
    last_message_post = fields.Datetime(string="Last Message")
    last_message_by = fields.Many2one(comodel_name="res.partner", ondelete="set null")
    is_participant = fields.Boolean(
        string="I participate", compute="_compute_is_participant"
    )

    message_count = fields.Integer(compute="_compute_message_count", compute_sudo=True)
    message_needaction_count = fields.Integer(
        compute="_compute_message_count", compute_sudo=True
    )
    display_name = fields.Char(compute="_compute_display_name")

    message_date = fields.Char(compute="_compute_message_date")
    message_date_display = fields.Char(compute="_compute_message_date")

    def _compute_message_date(self):
        for rec in self:
            if not rec.last_message_post:
                rec.update({"message_date": False, "message_date_display": False})
                continue
            message_date, date_display = _prepare_date_display(
                rec, rec.last_message_post
            )
            if message_date:
                message_date.replace(tzinfo=None)
            rec.update(
                {"message_date": message_date, "message_date_display": date_display}
            )

    @api.depends("author_id.name")
    @api.depends_context("message_move_wiz")
    def _compute_display_name(self):
        #  Currently using it only for Move Wizard!
        if not self._context.get("message_move_wiz"):
            return super()._compute_display_name()
        for rec in self:
            rec.display_name = f"{rec.name} - {rec.author_id.name}"

    @api.depends("message_ids")
    def _compute_message_count(self):
        """
        Compute count messages.
        All messages except for notifications are counted
        """
        for rec in self:
            message_ids = rec.message_ids.filtered(
                lambda msg: msg.message_type != "notification"
            )
            message_needaction = message_ids.filtered(lambda msg: msg.needaction)
            rec.update(
                {
                    "message_count": len(message_ids),
                    "message_needaction_count": len(message_needaction),
                }
            )

    def _compute_is_participant(self):
        """Compute partner is participant"""
        my_id = self.env.user.partner_id.id
        for rec in self:
            rec.is_participant = my_id in rec.partner_ids.ids

    def join(self):
        """Partner joining to conversation"""
        self.ensure_one()
        self.update({"partner_ids": [(4, self.env.user.partner_id.id)]})

    def leave(self):
        """Partner leaving from conversation"""
        self.ensure_one()
        self.sudo().update({"partner_ids": [(3, self.env.user.partner_id.id)]})
        return self.env["ir.actions.act_window"]._for_xml_id(
            "prt_mail_messages.action_conversations"
        )

    # -- Create
    @api.model_create_multi
    def create(self, vals_list):
        # Set current user as author if not defined.
        # Use current date as firs message post
        author_id = self.env.user.partner_id.id
        for vals in filter(lambda val: not val.get("author_id", False), vals_list):
            vals.update({"author_id": author_id})
        res = super(Conversation, self.sudo()).create(vals_list)
        # Subscribe participants
        res.message_subscribe(partner_ids=res.partner_ids.ids)
        return res

    def write(self, vals):
        # Use 'skip_followers_test=True' in context
        # to skip checking for followers/participants
        result = super().write(vals)
        only_conversation = self._context.get("only_conversation", False)
        if "active" in vals.keys() and not only_conversation:
            for rec in self:
                rec.archive_conversation_message(vals.get("active"))

        if self._context.get("skip_followers_test", False):
            # Skip checking for followers/participants
            return result

        # Check if participants changed
        for rec in self:
            msg_partner_ids = rec.message_partner_ids.ids
            partner_ids = rec.partner_ids.ids
            # New followers added?
            followers_add = list(
                filter(lambda p: p not in msg_partner_ids, partner_ids)
            )
            if followers_add:
                rec.message_subscribe(partner_ids=followers_add)

            # Existing followers removed?
            followers_remove = list(
                filter(lambda p: p not in partner_ids, msg_partner_ids)
            )
            if followers_remove:
                rec.message_unsubscribe(partner_ids=followers_remove)

        return result

    def archive_conversation_message(self, active_state):
        """Set archive state for related mail messages"""
        messages = self.env["mail.message"].search(
            [
                ("active", "=", not active_state),
                ("model", "=", self._name),
                ("res_id", "=", self.id),
                ("message_type", "!=", "notification"),
            ]
        )
        msg_vals = {"active": active_state}
        if active_state:
            msg_vals.update(delete_uid=False, delete_date=False)
        messages.write(msg_vals)

    # -- Search for partners by email.
    @api.model
    def partner_by_email(self, email_addresses):
        """
        Override this method to implement custom search
         (e.g. if using prt_phone_numbers module)
        :param list email_addresses: List of email addresses
        :return: res.partner obj if found.
        Please pay attention to the fact that only
         the first (newest) partner found is returned!
        """
        # Use loop with '=ilike' to resolve MyEmail@GMail.com cases
        res_partner_obj = self.env["res.partner"]
        for address in email_addresses:
            partner = res_partner_obj.search(
                [("email", "=ilike", address)], limit=1, order="id desc"
            )
            if partner:
                return partner

    @api.model
    def get_or_create_partner_id_by_email(self, email):
        """
        Get or create partner id
        :param str email: email address
        :rtype: int
        :return: partner id
        """
        if not email:
            return False
        res_partner_obj = self.env["res.partner"]
        parsed_name, parsed_email = parse_contact_from_email(email)
        partner = self.partner_by_email([parsed_email])
        if partner:
            return partner.id
        category = self.env.ref(
            "prt_mail_messages.cetmix_conversations_partner_cat",
            raise_if_not_found=False,
        )
        create_values = {
            "name": parsed_name or parsed_email,
            "category_id": [(4, category.id)] if category else False,
        }
        if parsed_email:
            create_values["email"] = parsed_email
        return res_partner_obj.create(create_values).id

    @api.model
    def prepare_partner_ids(self, email_list):
        """
        Prepare set of partner ids
        :param list email_list: list of email addresses
        :rtype: set
        :return: set of partner ids
        """
        if not email_list:
            return set()
        return {
            self.get_or_create_partner_id_by_email(email)
            for email in email_split_and_format(email_list)
        }

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        """Parse incoming email"""
        custom_values = custom_values or {}
        partner_ids = set()

        # 1. Check for author. If does not exist create new partner.
        author_id = msg_dict.get("author_id")
        email_from = msg_dict.get("email_from")
        if not author_id and email_from:
            author_id = self.get_or_create_partner_id_by_email(email_from)
            # Update message author
            msg_dict.update({"author_id": author_id})

        # Append author to participants (partners)
        partner_ids.add(author_id)

        # To
        partner_ids |= self.prepare_partner_ids(msg_dict.get("to"))
        # Cc
        partner_ids |= self.prepare_partner_ids(msg_dict.get("cc"))

        # Update custom values
        custom_values.update(
            {
                "name": msg_dict.get("subject", "").strip(),
                "author_id": author_id,
                "partner_ids": [(4, pid) for pid in partner_ids if pid],
            }
        )
        return super(
            Conversation, self.with_context(mail_create_nolog=True)
        ).message_new(msg_dict, custom_values)
