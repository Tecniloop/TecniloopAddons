# Copyright 2026 APEN Solutions
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.en.html).

from odoo import api, models
from odoo.osv import expression
from odoo.tools import escape_psql


class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.model
    def _search_get_detail(self, website, order, options):
        """Extend website product search to include brand and attribute values.

        Important note about Odoo's fuzzy search:
        - `website` may use pg_trgm to enumerate candidate words for fuzzy matching.
        - That enumeration currently supports indirect joins for One2many and Many2many,
          but not for Many2one relational fields like ``product_brand_id.name``.
        - Adding ``product_brand_id.name`` to ``search_fields`` can therefore crash the
          autocomplete when pg_trgm is enabled.

        To stay compatible, we add our extra criteria through ``search_extra`` (extra
        subdomain per token) instead of adding Many2one dot-paths to ``search_fields``.
        """
        detail = super()._search_get_detail(website, order, options)

        previous_extra = detail.get("search_extra")

        def _extra(env, search_term):
            term = escape_psql(search_term or "")
            ours = expression.OR([
                [("product_brand_id.name", "ilike", term)],
                [("attribute_line_ids.value_ids.name", "ilike", term)],
            ])
            previous = previous_extra(env, search_term) if previous_extra else []
            if previous:
                return expression.OR([previous, ours])
            return ours

        detail["search_extra"] = _extra
        return detail
