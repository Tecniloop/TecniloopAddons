# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo.addons.base.tests.common import BaseCommon
from odoo.exceptions import UserError
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestIcecatManufacturer(BaseCommon):
    def test_manufacturer_name_uniqueness(self):
        self.env["icecat.manufacturer"].create({"name": "Acme"})
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env["icecat.manufacturer"].create({"name": "Acme"})

    def test_brand_count(self):
        manufacturer = self.env["icecat.manufacturer"].create({"name": "Acme"})
        self.assertEqual(manufacturer.brand_count, 0)
        self.env["product.brand"].create(
            {"name": "Acme Brand", "icecat_manufacturer_id": manufacturer.id}
        )
        self.assertEqual(manufacturer.brand_count, 1)


@tagged("post_install", "-at_install")
class TestIcecatCategory(BaseCommon):
    def test_get_or_create_category_is_idempotent(self):
        icecat_category_model = self.env["icecat.category"]
        first = icecat_category_model.get_or_create_category("555", "Widgets")
        second = icecat_category_model.get_or_create_category("555", "Widgets")
        self.assertEqual(first.id, second.id)
        self.assertEqual(icecat_category_model.search_count([("icecat_id", "=", "555")]), 1)

    def test_get_or_create_category_updates_name(self):
        icecat_category_model = self.env["icecat.category"]
        category = icecat_category_model.get_or_create_category("555", "Widgets")
        renamed = icecat_category_model.get_or_create_category("555", "Widgets & Gadgets")
        self.assertEqual(category.id, renamed.id)
        self.assertEqual(category.name, "Widgets & Gadgets")

    def test_icecat_id_uniqueness(self):
        self.env["icecat.category"].create({"icecat_id": "1", "name": "Root"})
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env["icecat.category"].create({"icecat_id": "1", "name": "Root Again"})

    def test_get_or_create_product_category_builds_parent_chain(self):
        icecat_category_model = self.env["icecat.category"]
        parent = icecat_category_model.create({"icecat_id": "1", "name": "Electronics"})
        child = icecat_category_model.create(
            {"icecat_id": "2", "name": "Widgets", "parent_id": parent.id}
        )
        product_categ = child._get_or_create_product_category()
        self.assertEqual(product_categ.name, "Widgets")
        self.assertEqual(product_categ.parent_id.name, "Electronics")
        # calling it again must reuse the same records, not duplicate them
        self.assertEqual(child._get_or_create_product_category(), product_categ)
        self.assertEqual(parent._get_or_create_product_category(), product_categ.parent_id)

    def test_get_or_create_ecommerce_category_builds_parent_chain(self):
        icecat_category_model = self.env["icecat.category"]
        parent = icecat_category_model.create({"icecat_id": "10", "name": "Electronics"})
        child = icecat_category_model.create(
            {"icecat_id": "20", "name": "Widgets", "parent_id": parent.id}
        )
        ecommerce_categ = child._get_or_create_ecommerce_category()
        self.assertEqual(ecommerce_categ.name, "Widgets")
        self.assertEqual(ecommerce_categ.parent_id.name, "Electronics")


@tagged("post_install", "-at_install")
class TestProductBrandIcecat(BaseCommon):
    def test_brand_links_to_manufacturer(self):
        manufacturer = self.env["icecat.manufacturer"].create({"name": "Acme"})
        brand = self.env["product.brand"].create(
            {"name": "Acme Brand", "icecat_manufacturer_id": manufacturer.id}
        )
        self.assertEqual(brand.icecat_manufacturer_id, manufacturer)
        self.assertEqual(brand.icecat_bulk_state, "none")

    def test_bulk_import_start_requires_manufacturer(self):
        brand = self.env["product.brand"].create({"name": "No Manufacturer Brand"})
        with self.assertRaises(UserError):
            brand.action_icecat_bulk_import_start()

    def test_bulk_import_start_requires_supplier_id(self):
        manufacturer = self.env["icecat.manufacturer"].create({"name": "Acme"})
        brand = self.env["product.brand"].create(
            {"name": "Acme Brand", "icecat_manufacturer_id": manufacturer.id}
        )
        with self.assertRaises(UserError):
            brand.action_icecat_bulk_import_start()
