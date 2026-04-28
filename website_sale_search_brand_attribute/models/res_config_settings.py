# Copyright 2026 APEN Solutions
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.en.html).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    website_search_brand_name = fields.Boolean(
        string="Search brand name",
        default=True,
        config_parameter="website_sale_search_brand_attribute.search_brand_name",
    )
    website_search_brand_description = fields.Boolean(
        string="Search brand description",
        default=True,
        config_parameter="website_sale_search_brand_attribute.search_brand_description",
    )
    website_search_attribute_values = fields.Boolean(
        string="Search attribute values",
        default=True,
        config_parameter="website_sale_search_brand_attribute.search_attribute_values",
    )
    website_search_attribute_names = fields.Boolean(
        string="Search attribute names",
        default=True,
        config_parameter="website_sale_search_brand_attribute.search_attribute_names",
    )
    website_search_variant_attribute_values = fields.Boolean(
        string="Search variant-level attribute values",
        default=True,
        config_parameter="website_sale_search_brand_attribute.search_variant_attribute_values",
    )
    website_search_product_tags = fields.Boolean(
        string="Search product tags",
        default=True,
        config_parameter="website_sale_search_brand_attribute.search_product_tags",
    )
    website_search_website_categories = fields.Boolean(
        string="Search website categories",
        default=True,
        config_parameter="website_sale_search_brand_attribute.search_website_categories",
    )
    website_search_parent_website_categories = fields.Boolean(
        string="Search parent website categories",
        default=True,
        config_parameter="website_sale_search_brand_attribute.search_parent_website_categories",
    )
    website_search_visible_attributes_only = fields.Boolean(
        string="Only search visible attributes",
        default=True,
        config_parameter="website_sale_search_brand_attribute.search_visible_attributes_only",
    )
    website_search_prioritize_extra_matches = fields.Boolean(
        string="Prioritize extra matches",
        default=True,
        config_parameter="website_sale_search_brand_attribute.search_prioritize_extra_matches",
    )
