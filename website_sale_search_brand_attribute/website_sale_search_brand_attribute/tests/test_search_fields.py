# Copyright 2026 APEN Solutions
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.en.html).

from odoo.tests.common import SavepointCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestProductTemplateSearchFields(SavepointCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env.ref("website.default_website")

    def test_search_get_detail_uses_search_extra_for_brand_and_attribute_values(self):
        options = {
            "displayImage": False,
            "displayDescription": False,
            "displayExtraLink": False,
            "displayDetail": False,
            "category": None,
            "tags": None,
            "min_price": None,
            "max_price": None,
            "attrib_values": None,
        }
        detail = self.env["product.template"]._search_get_detail(
            self.website, order="name asc", options=options
        )

        # Avoid Many2one dot-path in search_fields to stay compatible with trigram fuzzy enumeration
        # (pg_trgm path doesn't join Many2one tables).
        self.assertNotIn("product_brand_id.name", detail.get("search_fields", []))

        search_extra = detail.get("search_extra")
        self.assertTrue(callable(search_extra))

        domain = search_extra(self.env, "Acme")
        # Domain is an expression list; ensure our criteria are present.
        self.assertIn(("product_brand_id.name", "ilike", "Acme"), domain)
        self.assertIn(("attribute_line_ids.value_ids.name", "ilike", "Acme"), domain)
