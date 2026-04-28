# Copyright 2026 APEN Solutions
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.en.html).

from odoo.osv import expression
from odoo.addons.website_sale.controllers.main import WebsiteSale as WebsiteSaleController


class WebsiteSale(WebsiteSaleController):
    def _add_search_subdomains_hook(self, search):
        """Extend /shop search to include brand and attribute values.

        The core implementation builds an OR domain per token (split by spaces)
        and calls this hook with each token. We add additional subdomains so
        the shop search matches:
          * product brand (product_brand_id.name)
          * attribute values (attribute_line_ids.value_ids.name)
        """
        extra_subdomain = super()._add_search_subdomains_hook(search) or []
        additional = expression.OR([
            [("product_brand_id.name", "ilike", search)],
            [("attribute_line_ids.value_ids.name", "ilike", search)],
        ])

        if extra_subdomain:
            return expression.OR([extra_subdomain, additional])
        return additional
