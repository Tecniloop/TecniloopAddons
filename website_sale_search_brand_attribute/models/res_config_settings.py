# Copyright 2026 APEN Solutions
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.en.html).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    website_search_brand_name = fields.Boolean(
        related="website_id.search_brand_name", readonly=False
    )
    website_search_brand_description = fields.Boolean(
        related="website_id.search_brand_description", readonly=False
    )
    website_search_attribute_values = fields.Boolean(
        related="website_id.search_attribute_values", readonly=False
    )
    website_search_attribute_names = fields.Boolean(
        related="website_id.search_attribute_names", readonly=False
    )
    website_search_variant_attribute_values = fields.Boolean(
        related="website_id.search_variant_attribute_values", readonly=False
    )
    website_search_product_tags = fields.Boolean(
        related="website_id.search_product_tags", readonly=False
    )
    website_search_website_categories = fields.Boolean(
        related="website_id.search_website_categories", readonly=False
    )
    website_search_parent_website_categories = fields.Boolean(
        related="website_id.search_parent_website_categories", readonly=False
    )
    website_search_visible_attributes_only = fields.Boolean(
        related="website_id.search_visible_attributes_only", readonly=False
    )
    website_search_prioritize_extra_matches = fields.Boolean(
        related="website_id.search_prioritize_extra_matches", readonly=False
    )
