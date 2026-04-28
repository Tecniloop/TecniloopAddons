# Copyright 2026 APEN Solutions
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.en.html).

from odoo.fields import Command
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestWebsiteShopSearch(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.website = cls.env.ref("website.default_website")

        # Create a brand (from website_product_brands)
        cls.brand = cls.env["wk.product.brand"].create({
            "name": "Acme",
            "is_published": True,
        })

        # Create an attribute + value
        cls.attribute = cls.env["product.attribute"].create({
            "name": "Color",
        })
        cls.value_red = cls.env["product.attribute.value"].create({
            "name": "Red",
            "attribute_id": cls.attribute.id,
        })

        # Create a product template linked to the brand and the attribute value
        cls.product_tmpl = cls.env["product.template"].create({
            "name": "ZZZ Search Brand/Attr Product",
            "sale_ok": True,
            "list_price": 10.0,
            "product_brand_id": cls.brand.id,
            # Publish on website
            "is_published": True,
            "website_published": True,
            "attribute_line_ids": [
                Command.create({
                    "attribute_id": cls.attribute.id,
                    "value_ids": [Command.set(cls.value_red.ids)],
                }),
            ],
        })

    def _assert_product_listed(self, response_text):
        self.assertIn(self.product_tmpl.name, response_text)

    def test_shop_search_by_brand_name(self):
        resp = self.url_open("/shop?search=Acme")
        self._assert_product_listed(resp.text)

    def test_shop_search_by_attribute_value(self):
        resp = self.url_open("/shop?search=Red")
        self._assert_product_listed(resp.text)
