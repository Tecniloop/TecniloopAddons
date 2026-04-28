# Copyright 2026 APEN Solutions
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.en.html).

from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale as WebsiteSaleController


class WebsiteSale(WebsiteSaleController):
    def _add_search_subdomains_hook(self, search):
        """Extend /shop search with configured extra product fields.

        Odoo core appends this return value with ``subdomains.extend(...)`` and
        later ORs every subdomain with product name/default-code/description.
        Therefore this hook returns a list of subdomains, not a composed domain.
        """
        subdomains = list(super()._add_search_subdomains_hook(search) or [])
        website = getattr(request, "website", None)
        if website:
            subdomains.extend(website._product_extra_search_subdomains(search))
        return subdomains

    def _shop_lookup_products(self, *args, **kwargs):
        """Prioritize products matching configured extra fields when possible.

        Odoo's SQL ordering cannot safely include term-specific CASE expressions
        for arbitrary relational fields. This hook keeps the base result/count
        untouched and only reorders the product recordset returned for display.
        """
        result = super()._shop_lookup_products(*args, **kwargs)
        try:
            fuzzy_search_term, product_count, products = result
        except (TypeError, ValueError):
            return result

        search = kwargs.get("search")
        website = kwargs.get("website") or getattr(request, "website", None)
        # Odoo 17/18 signature: (attrib_set, options, post, search, website)
        if not search and len(args) >= 4:
            search = args[3]
        if not website and len(args) >= 5:
            website = args[4]

        if website and search and website._search_option_enabled("search_prioritize_extra_matches"):
            products = products.sorted(
                key=lambda product: website._product_extra_search_score(product, search),
                reverse=True,
            )
        return fuzzy_search_term, product_count, products
