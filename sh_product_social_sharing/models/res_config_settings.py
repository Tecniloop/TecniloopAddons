# -*- coding: utf-8 -*-
# Part of Softhealer Technologies.

from odoo import fields, models


class Website(models.Model):
    _inherit = "website"

    sh_prod_social_is_prod_social_sharing = fields.Boolean(
        string="Is Product Share On Social Media?")
    sh_prod_social_sharing_facebook = fields.Boolean(string="Facebook")
    sh_prod_social_sharing_twitter = fields.Boolean(string="Twitter")
    sh_prod_social_sharing_linkedin = fields.Boolean(string="LinkedIn")
    sh_prod_social_sharing_whatsapp = fields.Boolean(string="WhatsApp")
    sh_prod_social_sharing_email = fields.Boolean(string="Email")
    sh_prod_social_sharing_pinterest = fields.Boolean(string="Pinterest")
    sh_prod_social_sharing_reddit = fields.Boolean(string="Reddit")
    sh_prod_social_sharing_hacker_news = fields.Boolean(string="Hacker News")
    sh_prod_social_sharing_digg = fields.Boolean(string="Digg")
    sh_prod_social_sharing_tumblr = fields.Boolean(string="Tumblr")

    sh_prod_social_sharing_style = fields.Selection([
        ("style_1", "Style 1"),
        ("style_2", "Style 2"),
        ("style_3", "Style 3"),
        ("style_4", "Style 4"),
        ("style_5", "Style 5"),
        ("style_6", "Style 6"),
        ("style_7", "Style 7"),
        ("style_8", "Style 8"),
        ("style_9", "Style 9"),
        ("style_10", "Style 10"),
        ("style_11", "Style 11"),
    ], string="Style ", default="style_1")


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    sh_prod_social_is_prod_social_sharing = fields.Boolean(
        string="Is Product Share On Social Media?",
        related="website_id.sh_prod_social_is_prod_social_sharing",
        readonly=False)
    sh_prod_social_sharing_facebook = fields.Boolean(
        string="Facebook",
        related="website_id.sh_prod_social_sharing_facebook",
        readonly=False)
    sh_prod_social_sharing_twitter = fields.Boolean(
        string="Twitter",
        related="website_id.sh_prod_social_sharing_twitter",
        readonly=False)
    sh_prod_social_sharing_linkedin = fields.Boolean(
        string="LinkedIn",
        related="website_id.sh_prod_social_sharing_linkedin",
        readonly=False)
    sh_prod_social_sharing_whatsapp = fields.Boolean(
        string="WhatsApp",
        related="website_id.sh_prod_social_sharing_whatsapp",
        readonly=False)
    sh_prod_social_sharing_email = fields.Boolean(
        string="Email",
        related="website_id.sh_prod_social_sharing_email",
        readonly=False)
    sh_prod_social_sharing_pinterest = fields.Boolean(
        string="Pinterest",
        related="website_id.sh_prod_social_sharing_pinterest",
        readonly=False)
    sh_prod_social_sharing_reddit = fields.Boolean(
        string="Reddit",
        related="website_id.sh_prod_social_sharing_reddit",
        readonly=False)
    sh_prod_social_sharing_hacker_news = fields.Boolean(
        string="Hacker News",
        related="website_id.sh_prod_social_sharing_hacker_news",
        readonly=False)

    sh_prod_social_sharing_digg = fields.Boolean(
        string="Digg",
        related="website_id.sh_prod_social_sharing_digg",
        readonly=False)
    sh_prod_social_sharing_tumblr = fields.Boolean(
        string="Tumblr",
        related="website_id.sh_prod_social_sharing_tumblr",
        readonly=False)

    sh_prod_social_sharing_style = fields.Selection(
        string="Style",
        related="website_id.sh_prod_social_sharing_style",
        readonly=False)
