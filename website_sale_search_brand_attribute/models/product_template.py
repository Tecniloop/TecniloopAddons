# Copyright 2026 APEN Solutions
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.en.html).

from odoo import api, models
from odoo.osv import expression


class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.model
    def _search_get_detail(self, website, order, options):
        """Extend generic website product search with configured extra fields.

        We keep these criteria in ``search_extra`` instead of ``search_fields``.
        This avoids pg_trgm/fuzzy-search crashes on Many2one dot paths such as
        brand fields while still allowing exact token matching.
        """
        detail = super()._search_get_detail(website, order, options)
        previous_extra = detail.get("search_extra")

        def _extra(env, search_term):
            ours = website._product_extra_search_domain(search_term, require_all_words=True)
            previous = previous_extra(env, search_term) if previous_extra else []
            if previous and ours:
                return expression.OR([previous, ours])
            return previous or ours

        detail["search_extra"] = _extra
        return detail
