# Copyright 2026 APEN Solutions
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.en.html).

from odoo import fields, models
from odoo.osv import expression
from odoo.tools import escape_psql


class Website(models.Model):
    _inherit = "website"

    search_brand_name = fields.Boolean(default=True)
    search_brand_description = fields.Boolean(default=True)
    search_attribute_values = fields.Boolean(default=True)
    search_attribute_names = fields.Boolean(default=True)
    search_variant_attribute_values = fields.Boolean(default=True)
    search_product_tags = fields.Boolean(default=True)
    search_website_categories = fields.Boolean(default=True)
    search_parent_website_categories = fields.Boolean(default=True)
    search_visible_attributes_only = fields.Boolean(default=True)
    search_prioritize_extra_matches = fields.Boolean(default=True)

    def _search_has_path(self, model_name, path):
        """Return whether a dotted ORM path exists from ``model_name``.

        Domains are built dynamically because brand addons in the wild use
        different models/field names. Checking paths before injecting them keeps
        the module safe across forks of ``website_product_brands``.
        """
        if model_name not in self.env.registry:
            return False
        current_model = self.env[model_name]
        for part in path.split("."):
            field = current_model._fields.get(part)
            if not field:
                return False
            if field.relational and getattr(field, "comodel_name", None):
                if field.comodel_name not in self.env.registry:
                    return False
                current_model = self.env[field.comodel_name]
        return True

    def _search_brand_fields(self):
        Product = self.env["product.template"]
        fields_to_try = ["product_brand_id", "brand_id", "product_brand_ids", "brand_ids"]
        name_fields = ["name", "display_name"]
        description_fields = ["description", "description_sale", "website_description"]
        result = []
        for brand_field in fields_to_try:
            field = Product._fields.get(brand_field)
            if not field or not getattr(field, "comodel_name", None):
                continue
            if field.comodel_name not in self.env.registry:
                continue
            Brand = self.env[field.comodel_name]
            if self.search_brand_name:
                result += [f"{brand_field}.{fname}" for fname in name_fields if fname in Brand._fields]
            if self.search_brand_description:
                result += [
                    f"{brand_field}.{fname}"
                    for fname in description_fields
                    if fname in Brand._fields
                ]
        return result

    def _search_attribute_visibility_domain(self, attr_path):
        if not self.search_visible_attributes_only:
            return []
        hidden_path = f"{attr_path}.visibility"
        if self._search_has_path("product.template", hidden_path):
            return [(hidden_path, "!=", "hidden")]
        return []

    def _product_extra_search_subdomains(self, search_term):
        """Return a list of valid extra-search subdomains for one token.

        WebsiteSale._add_search_subdomains_hook must return a list of
        independent domains. Core Odoo appends that list to the normal product
        name/default-code/description search before OR-ing the items.
        """
        self.ensure_one()
        word = escape_psql(search_term or "").strip()
        if not word:
            return []

        subdomains = []

        for field_path in self._search_brand_fields():
            if self._search_has_path("product.template", field_path):
                subdomains.append([(field_path, "ilike", word)])

        if self.search_attribute_values and self._search_has_path(
            "product.template", "attribute_line_ids.value_ids.name"
        ):
            subdomains.append(expression.AND([
                self._search_attribute_visibility_domain("attribute_line_ids.attribute_id"),
                [("attribute_line_ids.value_ids.name", "ilike", word)],
            ]))

        if self.search_attribute_names and self._search_has_path(
            "product.template", "attribute_line_ids.attribute_id.name"
        ):
            subdomains.append(expression.AND([
                self._search_attribute_visibility_domain("attribute_line_ids.attribute_id"),
                [("attribute_line_ids.attribute_id.name", "ilike", word)],
            ]))

        if self.search_variant_attribute_values and self._search_has_path(
            "product.template",
            "product_variant_ids.product_template_attribute_value_ids.product_attribute_value_id.name",
        ):
            subdomains.append([
                (
                    "product_variant_ids.product_template_attribute_value_ids.product_attribute_value_id.name",
                    "ilike",
                    word,
                )
            ])
            if self.search_attribute_names and self._search_has_path(
                "product.template",
                "product_variant_ids.product_template_attribute_value_ids.attribute_id.name",
            ):
                subdomains.append([
                    (
                        "product_variant_ids.product_template_attribute_value_ids.attribute_id.name",
                        "ilike",
                        word,
                    )
                ])

        if self.search_product_tags and self._search_has_path("product.template", "website_tag_ids.name"):
            subdomains.append([("website_tag_ids.name", "ilike", word)])

        if self.search_website_categories and self._search_has_path(
            "product.template", "public_categ_ids.name"
        ):
            subdomains.append([("public_categ_ids.name", "ilike", word)])

        if self.search_parent_website_categories and self._search_has_path(
            "product.template", "public_categ_ids.parent_id.name"
        ):
            subdomains.append([("public_categ_ids.parent_id.name", "ilike", word)])

        if self.search_parent_website_categories and "product.public.category" in self.env.registry:
            Category = self.env["product.public.category"]
            categories = Category.search([("name", "ilike", word)])
            if categories:
                subdomains.append([("public_categ_ids", "child_of", categories.ids)])

        return subdomains

    def _product_extra_search_domain(self, search_term, require_all_words=False):
        """Build a composed domain from extra product-search subdomains."""
        self.ensure_one()
        term = escape_psql(search_term or "").strip()
        if not term:
            return []
        words = [word for word in term.split() if word]
        if not require_all_words or len(words) <= 1:
            words = [term]

        domains_by_word = []
        for word in words:
            subdomains = self._product_extra_search_subdomains(word)
            if subdomains:
                domains_by_word.append(expression.OR(subdomains))

        return expression.AND(domains_by_word) if domains_by_word else []

    def _product_extra_search_score(self, product, search_term):
        """Small Python-side rank used to prioritize configured extra matches.

        This is intentionally conservative: it reorders only the product recordset
        returned by Odoo, and does not alter access rules or the base shop domain.
        """
        term = (search_term or "").lower().strip()
        if not term or not self.search_prioritize_extra_matches:
            return 0
        words = [term] + [w for w in term.split() if w != term]

        chunks = []
        for field_path in self._search_brand_fields():
            value = product
            for part in field_path.split("."):
                value = value.mapped(part) if hasattr(value, "mapped") else False
                if not value:
                    break
            if value:
                chunks.append(" ".join(value.mapped("display_name")) if hasattr(value, "mapped") else str(value))
        if self.search_attribute_values:
            chunks += product.attribute_line_ids.mapped("value_ids.name")
        if self.search_attribute_names:
            chunks += product.attribute_line_ids.mapped("attribute_id.name")
        if self.search_variant_attribute_values:
            chunks += product.product_variant_ids.mapped(
                "product_template_attribute_value_ids.product_attribute_value_id.name"
            )
        if self.search_product_tags and "website_tag_ids" in product._fields:
            chunks += product.mapped("website_tag_ids.name")
        if self.search_website_categories and "public_categ_ids" in product._fields:
            chunks += product.mapped("public_categ_ids.name")
        if self.search_parent_website_categories and "public_categ_ids" in product._fields:
            chunks += product.mapped("public_categ_ids.parent_id.name")

        haystack = " ".join(chunks).lower()
        score = 0
        for index, word in enumerate(words):
            if word and word in haystack:
                score += 100 if index == 0 else 20
        return score
