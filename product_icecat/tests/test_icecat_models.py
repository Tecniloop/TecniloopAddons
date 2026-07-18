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

    def _patch_suppliers_list(self, rows):
        """Patch the Icecat client used by icecat.manufacturer so that
        ``iter_suppliers`` yields ``rows`` without any HTTP call."""
        from unittest.mock import MagicMock, patch

        client = MagicMock()
        client.iter_suppliers.side_effect = lambda: iter(rows)
        return patch(
            "odoo.addons.product_icecat.models.icecat_manufacturer.get_client_from_env",
            return_value=client,
        )

    def test_bulk_import_start_resolves_missing_supplier_id(self):
        manufacturer = self.env["icecat.manufacturer"].create({"name": "acme"})
        brand = self.env["product.brand"].create(
            {"name": "Acme Brand", "icecat_manufacturer_id": manufacturer.id}
        )
        # name match is case-insensitive against Icecat's spelling
        with self._patch_suppliers_list(
            [{"icecat_id": "1", "name": "HP"}, {"icecat_id": "99", "name": "Acme"}]
        ):
            brand.action_icecat_bulk_import_start()
        self.assertEqual(manufacturer.icecat_supplier_id, "99")
        self.assertEqual(brand.icecat_bulk_state, "scanning")

    def test_bulk_import_start_errors_when_name_not_in_suppliers_list(self):
        manufacturer = self.env["icecat.manufacturer"].create({"name": "Nonexistent Vendor"})
        brand = self.env["product.brand"].create(
            {"name": "Ghost Brand", "icecat_manufacturer_id": manufacturer.id}
        )
        with self._patch_suppliers_list([{"icecat_id": "1", "name": "HP"}]):
            with self.assertRaises(UserError):
                brand.action_icecat_bulk_import_start()
        self.assertFalse(manufacturer.icecat_supplier_id)

    def test_action_fetch_supplier_id(self):
        manufacturer = self.env["icecat.manufacturer"].create({"name": "Lenovo"})
        with self._patch_suppliers_list([{"icecat_id": "734", "name": "Lenovo"}]):
            manufacturer.action_fetch_supplier_id()
        self.assertEqual(manufacturer.icecat_supplier_id, "734")

    def test_sync_from_icecat_creates_and_updates(self):
        manufacturer_model = self.env["icecat.manufacturer"]
        # existing record without ID (matched by name, case-insensitively)
        no_id = manufacturer_model.create({"name": "acme"})
        # existing record matched by ID whose name drifted from Icecat's
        renamed = manufacturer_model.create({"name": "Lenovo Group", "icecat_supplier_id": "734"})
        rows = [
            {"icecat_id": "1", "name": "HP"},
            {"icecat_id": "99", "name": "Acme"},
            {"icecat_id": "734", "name": "Lenovo"},
        ]
        with self._patch_suppliers_list(rows):
            manufacturer_model.action_sync_from_icecat()
        self.assertEqual(no_id.icecat_supplier_id, "99")
        self.assertEqual(renamed.name, "Lenovo")
        created = manufacturer_model.search([("name", "=", "HP")])
        self.assertEqual(created.icecat_supplier_id, "1")

    def test_sync_from_icecat_is_idempotent(self):
        manufacturer_model = self.env["icecat.manufacturer"]
        rows = [{"icecat_id": "1", "name": "HP"}, {"icecat_id": "99", "name": "Acme"}]
        with self._patch_suppliers_list(rows):
            manufacturer_model.action_sync_from_icecat()
            count_after_first = manufacturer_model.search_count([])
            manufacturer_model.action_sync_from_icecat()
        self.assertEqual(manufacturer_model.search_count([]), count_after_first)
