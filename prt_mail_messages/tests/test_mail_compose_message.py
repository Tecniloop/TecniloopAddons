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

import re

from lxml.html import fromstring

from odoo.tests import Form
from odoo.tools import misc

from .common import MailMessageCommon


class TestMailComposeMessage(MailMessageCommon):
    """
    TEST 1 : Check valid fields value in forward mode
    TEST 2 : Check behavior get_record_data function
    TEST 3 : Check preparing partners by parent mail message record
    TEST 4 : Check default signature location
    """

    # -- TEST 1 : Check valid fields value in forward mode
    def test_valid_forward_reference(self):
        """Check field values in forward mode"""

        # 'compose' mode
        # as if the "mail" button is clicked on Partner form
        with Form(
            self.env["mail.compose.message"].with_context(
                default_wizard_mode="compose",
                default_model="res.partner",
                default_res_ids=self.res_partner_kate.ids,
            )
        ) as form:
            self.assertEqual(
                form.forward_ref,
                f"res.partner,{self.res_partner_kate.id}",
                f"Reference must be set to {self.res_partner_kate.name}",
            )

    # -- TEST 2 : Check preparing subject field
    def test_compose_message_record_data(self):
        """Check preparing subject field"""
        compose = (
            self.env["mail.compose.message"]
            .with_context(default_subject="Custom Subject")
            .create({})
        )
        self.assertEqual(
            compose.subject,
            "Custom Subject",
            msg="Subject value must be equal to 'Custom Subject'",
        )
        compose = self.env["mail.compose.message"].create(
            {"parent_id": self.mail_message_parent.id}
        )
        self.assertEqual(
            compose.record_name,
            "Kate",
            msg="Record Name must be equal to 'Kate'",
        )
        self.assertListEqual(
            compose.partner_ids.ids,
            [self.res_partner_kate.id, self.res_partner_mark.id],
            msg="Partners must be the same",
        )
        self.assertEqual(
            compose.model,
            "res.partner",
            msg="Model must be equal to 'res.partner'",
        )
        self.assertEqual(
            compose.res_ids,
            str(self.res_partner_kate.ids),
            msg=f"Res ID must be equal to {self.res_partner_kate.id}",
        )
        self.assertEqual(
            compose.subject,
            "Kate",
            msg="Subject value must be equal to 'Kate'",
        )
        compose = (
            self.env["mail.compose.message"]
            .with_context(default_wizard_mode="forward")
            .create({"model": "res.partner", "res_ids": self.res_partner_kate.ids})
        )
        self.assertEqual(
            compose.subject,
            "Fwd: Kate",
            msg="Subject value must be equal to 'Fwd: Kate'",
        )
        compose = (
            self.env["mail.compose.message"]
            .with_context(default_wizard_mode="quote")
            .create({"model": "res.partner", "res_ids": self.res_partner_kate.ids})
        )
        self.assertEqual(
            compose.subject, "Re: Kate", msg="Subject value must be equal to 'Re: Kate'"
        )

    # -- TEST 3 : Check preparing partners by parent mail message record
    def test_prepare_valid_record_partners(self):
        """Check preparing partners by parent mail message record"""
        parent = self.mail_message_parent
        MailCompose = self.env["mail.compose.message"]
        partner_ids = MailCompose._prepare_valid_record_partners(parent, [])
        partners = [(4, self.res_partner_kate.id), (4, self.res_partner_mark.id)]
        self.assertListEqual(partner_ids, partners, msg="Partners must be the same")
        partner_ids = MailCompose._prepare_valid_record_partners(
            parent, [(6, 0, self.res_partner_kate.ids)]
        )
        self.assertListEqual(
            partner_ids,
            [(6, 0, self.res_partner_kate.ids)] + partners,
            msg="Partners must be the same",
        )
        partner_ids = MailCompose.with_context(
            is_private=True
        )._prepare_valid_record_partners(parent, [])
        self.assertListEqual(
            partner_ids,
            partners + [(4, self.res_partner_ann.id)],
            msg="Partners must be the same",
        )

    # -- TEST 4 : Check default signature location
    def test_default_signature_location(self):
        """Check default signature location"""
        MailCompose = self.env["mail.compose.message"]
        ICPSudo = self.env["ir.config_parameter"].sudo()

        ICPSudo.set_param("cetmix.message_signature_location", "a")
        self.assertEqual(
            MailCompose._default_signature_location(),
            "a",
            msg="Default signature location must be equal to 'a' (Message bottom)",
        )
        ICPSudo.set_param("cetmix.message_signature_location", "b")
        self.assertEqual(
            MailCompose._default_signature_location(),
            "b",
            msg="Default signature location must be equal to 'a' (Before quote)",
        )
        ICPSudo.set_param("cetmix.message_signature_location", "n")
        self.assertEqual(
            MailCompose._default_signature_location(),
            "n",
            msg="Default signature location must be equal to 'n' (No signature)",
        )

    # -- TEST 5 : Test flow that prepared value for message quotation in composer
    def test_mail_compose_message_default_get_quote(self):
        """Test flow that prepared value for message quotation in composer"""
        parent = self.mail_message_parent
        context = parent.with_context(wizard_mode="quote").reply_prep_context()
        self.assertEqual(
            context.get("default_parent_id"),
            parent.id,
            f"'default_parent_id' must be equal to {parent.id}",
        )
        self.assertEqual(
            context.get("default_wizard_mode"),
            "quote",
            "'default_wizard_mode' must be equal to 'quote'",
        )

        composer = self.env["mail.compose.message"].with_context(**context).create({})
        self.assertIn("<blockquote", composer.body, "Body must contain the quote block")
        self.assertEqual(
            composer.wizard_mode, "quote", "Wizard mode value must be equal to 'quote'"
        )

    # -- TEST 6 : Test flow that prepared value for message forward in composer
    def test_mail_compose_message_default_get_forward(self):
        """Test flow that prepared value for message forward in composer"""
        parent = self.mail_message_parent
        context = parent.with_context(wizard_mode="forward").reply_prep_context()
        self.assertEqual(
            context.get("default_parent_id"),
            parent.id,
            f"'default_parent_id' must be equal to {parent.id}",
        )
        self.assertEqual(
            context.get("default_wizard_mode"),
            "forward",
            "'default_wizard_mode' must be equal to 'quote'",
        )

        composer = self.env["mail.compose.message"].with_context(**context).create({})
        self.assertFalse(composer.parent_id, msg="parent_id must be False")
        self.assertIn("<blockquote", composer.body, "Body must contain the quote block")

    # -- TEST 7 : Test flow that prepared quoted body
    def test_prepare_quoted_body(self):
        """Test flow when prepared quoted body"""
        parent = self.mail_message_parent
        parent.subject = "Test Subject"
        body = self.env["mail.compose.message"]._prepare_quoted_body(parent, True)

        date = misc.format_datetime(self.env, parent.date)
        match = re.search("Date: (.+?) <br/>", body)
        found = match.group(1)
        self.assertEqual(found, date, f"Date value must be equal to {date}")

        match = re.search("From: (.+?) <br/>", body)
        found = match.group(1)
        self.assertEqual(
            found,
            str(parent.author_display),
            f"From value must be equal to {parent.author_display}",
        )

        match = re.search("Subject: (.+?) <br/>", body)
        found = match.group(1)
        self.assertEqual(
            found,
            str(parent.subject),
            f"Subject value must be equal to {parent.subject}",
        )

    # -- TEST 8 : Test flow that trim block quote from message body
    def test_trim_quote_blocks(self):
        """Test flow that trim block quote from message body"""
        message_body = """<p style='margin:0px 0px 9px 0px; font-size:13px; font-family:"Lucida Grande", Helvetica, Verdana, Arial, sans-serif'>Test Message #3</p><br><blockquote style="border-style:none none none solid; padding:9px 18px 9px 18px; margin:0px 0px 18px 0px; border-left-color:rgb(249, 249, 249); border-left-width:5px; font-size:16.25px" data-o-mail-quote="1">----- Original message ----- <br> Date: 2023-11-25 16:47:30 <br> From: Administrator <br> Subject: Re: Fwd: Agrolait <br><br><p style='margin:0px 0px 9px 0px; font-size:13px; font-family:"Lucida Grande", Helvetica, Verdana, Arial, sans-serif'>Test Message #2</p><hr style="border-style:solid none none none; margin:18px 0 18px 0; border-top-color:rgb(249, 249, 249); border-top-width:1px; border-left-color:currentcolor; border-left-width:0px; border-bottom-color:currentcolor; border-bottom-width:0px; border-right-color:currentcolor; border-right-width:0px; height:0px"><br><br><blockquote style="border-style:none none none solid; padding:9px 18px 9px 18px; margin:0px 0px 18px 0px; border-left-color:rgb(249, 249, 249); border-left-width:5px; font-size:16.25px" data-o-mail-quote="1">----- Original message ----- <br> Date: 2023-11-25 16:47:11 <br> From: Administrator <br> Subject: Re: Fwd: Agrolait <br><br><p style='margin:0px 0px 9px 0px; font-size:13px; font-family:"Lucida Grande", Helvetica, Verdana, Arial, sans-serif'></p><p style='margin:0px 0px 9px 0px; font-size:13px; font-family:"Lucida Grande", Helvetica, Verdana, Arial, sans-serif'>Test Message #1</p><hr style="border-style:solid none none none; margin:18px 0 18px 0; border-top-color:rgb(249, 249, 249); border-top-width:1px; border-left-color:currentcolor; border-left-width:0px; border-bottom-color:currentcolor; border-bottom-width:0px; border-right-color:currentcolor; border-right-width:0px; height:0px"><br><blockquote style="border-style:none none none solid; padding:9px 18px 9px 18px; margin:0px 0px 18px 0px; border-left-color:rgb(249, 249, 249); border-left-width:5px; font-size:16.25px" data-o-mail-quote="1">----- Original message ----- <br> Date: 2023-11-19 15:40:37 <br> From: Administrator <br> Subject: Fwd: Agrolait <br><br><p style='margin:0px 0px 9px 0px; font-size:13px; font-family:"Lucida Grande", Helvetica, Verdana, Arial, sans-serif'>TEST<br></p><br><blockquote style="border-style:none none none solid; padding:9px 18px 9px 18px; margin:0px 0px 18px 0px; border-left-color:rgb(249, 249, 249); border-left-width:5px; font-size:16.25px" data-o-mail-quote="1">----- Original message ----- <br> Date: 11/16/2023 20:03:46 <br> From: Administrator <br> Subject: Re: Agrolait <br><br><p style='margin:0px; font-size:13px; font-family:"Lucida Grande", Helvetica, Verdana, Arial, sans-serif'>TESTSET<br></p></blockquote></blockquote></blockquote></blockquote>"""  # noqa
        expected_body = "<p>Hello World</p>"
        body = self.env["mail.compose.message"]._trim_quote_blocks(expected_body, 0)
        self.assertEqual(body, expected_body, "Values must be the same")

        expected_body = "<p>Hello World</p>"
        body = self.env["mail.compose.message"]._trim_quote_blocks(expected_body, 1)
        self.assertEqual(body, expected_body, "Values must be the same")

        body = self.env["mail.compose.message"]._trim_quote_blocks(message_body, 10)
        self.assertEqual(body, message_body, "Values must be the same")

        tree = fromstring(message_body)
        expected_blocks = tree.xpath("//blockquote")
        self.assertEqual(len(expected_blocks), 4, "Blocks count must be equal to 4")

        body = self.env["mail.compose.message"]._trim_quote_blocks(message_body, 0)
        tree = fromstring(body)
        blocks = tree.xpath("//blockquote")
        self.assertEqual(
            len(blocks), len(expected_blocks), "Blocks count must be the same"
        )

        body = self.env["mail.compose.message"]._trim_quote_blocks(message_body, 4)
        tree = fromstring(body)
        blocks = tree.xpath("//blockquote")
        self.assertEqual(
            len(blocks), len(expected_blocks), "Blocks count must be the same"
        )

        body = self.env["mail.compose.message"]._trim_quote_blocks(message_body, 3)
        tree = fromstring(body)
        blocks = tree.xpath("//blockquote")
        self.assertEqual(len(blocks), 3, "Blocks count must be equal to 3")

        body = self.env["mail.compose.message"]._trim_quote_blocks(message_body, 1)
        tree = fromstring(body)
        blocks = tree.xpath("//blockquote")
        self.assertEqual(len(blocks), 1, "Blocks count must be equal to 1")

    # -- TEST 9 : Test flow that prepares subject with prefix
    def test_prepare_subject_with_prefix(self):
        """Test flow that prepares subject with prefix"""
        MailCompose = self.env["mail.compose.message"]

        # Test empty/None subject cases
        result = MailCompose._prepare_subject_with_prefix("forward", "")
        self.assertEqual(result, "", "Empty subject should return unchanged")
        result = MailCompose._prepare_subject_with_prefix("quote", "")
        self.assertEqual(result, "", "Empty subject should return unchanged")

        # Test forward mode - subject without prefix
        result = MailCompose._prepare_subject_with_prefix("forward", "Test Subject")
        self.assertEqual(
            result,
            "Fwd: Test Subject",
            "Forward mode should add 'Fwd:' prefix when missing",
        )

        # Test forward mode - subject with prefix already present
        result = MailCompose._prepare_subject_with_prefix(
            "forward", "Fwd: Test Subject"
        )
        self.assertEqual(
            result,
            "Fwd: Test Subject",
            "Forward mode should not duplicate prefix when already present",
        )

        # Test forward mode - subject with prefix in different case
        result = MailCompose._prepare_subject_with_prefix(
            "forward", "FWD: Test Subject"
        )
        self.assertEqual(
            result,
            "FWD: Test Subject",
            "Forward mode should not duplicate prefix when present in different case",
        )
        result = MailCompose._prepare_subject_with_prefix(
            "forward", "fwd: Test Subject"
        )
        self.assertEqual(
            result,
            "fwd: Test Subject",
            "Forward mode should not duplicate prefix when present in lowercase",
        )

        # Test quote mode - subject without prefix
        result = MailCompose._prepare_subject_with_prefix("quote", "Test Subject")
        self.assertEqual(
            result,
            "Re: Test Subject",
            "Quote mode should add 'Re:' prefix when missing",
        )

        # Test quote mode - subject with prefix already present
        result = MailCompose._prepare_subject_with_prefix("quote", "Re: Test Subject")
        self.assertEqual(
            result,
            "Re: Test Subject",
            "Quote mode should not duplicate prefix when already present",
        )

        # Test quote mode - subject with prefix in different case
        result = MailCompose._prepare_subject_with_prefix("quote", "RE: Test Subject")
        self.assertEqual(
            result,
            "RE: Test Subject",
            "Quote mode should not duplicate prefix when present in different case",
        )
        result = MailCompose._prepare_subject_with_prefix("quote", "re: Test Subject")
        self.assertEqual(
            result,
            "re: Test Subject",
            "Quote mode should not duplicate prefix when present in lowercase",
        )

        # Test other wizard_mode values - should return unchanged
        result = MailCompose._prepare_subject_with_prefix("compose", "Test Subject")
        self.assertEqual(
            result,
            "Test Subject",
            "Compose mode should return subject unchanged",
        )
        result = MailCompose._prepare_subject_with_prefix(None, "Test Subject")
        self.assertEqual(
            result,
            "Test Subject",
            "None wizard_mode should return subject unchanged",
        )
        result = MailCompose._prepare_subject_with_prefix("invalid", "Test Subject")
        self.assertEqual(
            result,
            "Test Subject",
            "Invalid wizard_mode should return subject unchanged",
        )

        # Test edge cases with multiple prefixes
        result = MailCompose._prepare_subject_with_prefix("forward", "Re: Test Subject")
        self.assertEqual(
            result,
            "Fwd: Re: Test Subject",
            "Forward mode should add 'Fwd:' even if 'Re:' is present",
        )
        result = MailCompose._prepare_subject_with_prefix("quote", "Fwd: Test Subject")
        self.assertEqual(
            result,
            "Re: Fwd: Test Subject",
            "Quote mode should add 'Re:' even if 'Fwd:' is present",
        )
