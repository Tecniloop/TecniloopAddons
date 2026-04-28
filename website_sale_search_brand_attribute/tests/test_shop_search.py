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

        cls.brand = cls.env["wk.product.brand"].create({
            "name": "Acme",
            "is_published": True,
        })
        if "description" in cls.brand._fields:
            cls.brand.description = "Industrial premium brand"

        cls.attribute = cls.env["product.attribute"].create({
            "name": "Color",
        })
        cls.value_red = cls.env["product.attribute.value"].create({
            "name": "Red",
            "attribute_id": cls.attribute.id,
        })

        cls.public_category = cls.env["product.public.category"].create({"name": "Parent Outdoor"})
        cls.public_child = cls.env["product.public.category"].create({
            "name": "Child Hiking",
            "parent_id": cls.public_category.id,
        })

        product_vals = {
            "name": "ZZZ Search Brand/Attr Product",
            "sale_ok": True,
            "list_price": 10.0,
            "product_brand_id": cls.brand.id,
            "is_published": True,
            "website_published": True,
            "public_categ_ids": [Command.set(cls.public_child.ids)],
            "attribute_line_ids": [
                Command.create({
                    "attribute_id": cls.attribute.id,
                    "value_ids": [Command.set(cls.value_red.ids)],
                }),
            ],
        }
        if "website_tag_ids" in cls.env["product.template"]._fields:
            tag = cls.env["product.tag"].create({"name": "EcoTag"})
            product_vals["website_tag_ids"] = [Command.set(tag.ids)]
        cls.product_tmpl = cls.env["product.template"].create(product_vals)

    def _assert_product_listed(self, response_text):
        self.assertIn(self.product_tmpl.name, response_text)

    def test_shop_search_by_brand_name(self):
        resp = self.url_open("/shop?search=Acme")
        self._assert_product_listed(resp.text)

    def test_shop_search_by_attribute_value(self):
        resp = self.url_open("/shop?search=Red")
        self._assert_product_listed(resp.text)

    def test_shop_search_by_attribute_name(self):
        resp = self.url_open("/shop?search=Color")
        self._assert_product_listed(resp.text)

    def test_shop_search_by_parent_category(self):
        resp = self.url_open("/shop?search=Outdoor")
        self._assert_product_listed(resp.text)
