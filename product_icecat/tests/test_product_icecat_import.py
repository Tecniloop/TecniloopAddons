# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from unittest.mock import patch

from odoo.addons.base.tests.common import BaseCommon
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import TINY_PNG_BYTES, get_test_product


@tagged("post_install", "-at_install")
class TestIcecatCreateProduct(BaseCommon):
    """``product.template._icecat_create_product`` takes already-parsed
    data (see the shared-caller design in models/product_template.py), so
    it can be exercised directly without mocking any HTTP calls."""

    def setUp(self):
        super().setUp()
        self.manufacturer = self.env["icecat.manufacturer"].create(
            {
                "name": "Acme",
                "import_main_image": True,
                "import_gallery_images": True,
                "create_product_category": True,
                "create_ecommerce_category": True,
            }
        )
        self.brand = self.env["product.brand"].create(
            {"name": "Acme Brand", "icecat_manufacturer_id": self.manufacturer.id}
        )

    def _create_from_fixture(self, **overrides):
        icecat_product = get_test_product()
        vals = {
            "name": icecat_product.title,
            "part_number": icecat_product.prod_id,
            "ean": icecat_product.ean,
            "product_brand": self.brand,
            "icecat_id": icecat_product.icecat_id,
            "description_html": icecat_product.build_description_html(),
            "category_icecat_id": icecat_product.category_icecat_id,
            "category_name": icecat_product.category_name,
            "main_image_url": icecat_product.main_image_url,
            "gallery_image_urls": icecat_product.gallery_image_urls,
            "import_main_image": True,
            "import_gallery_images": True,
            "create_product_category": True,
            "create_ecommerce_category": True,
        }
        vals.update(overrides)
        with patch(
            "odoo.addons.product_icecat.models.product_template.ProductTemplate."
            "_icecat_download_image",
            return_value=TINY_PNG_BYTES,
        ):
            return self.env["product.template"]._icecat_create_product(**vals)

    def test_basic_fields(self):
        product = self._create_from_fixture()
        self.assertEqual(product.name, "Acme Widget Pro 15")
        self.assertEqual(product.default_code, "TEST-MPN-001")
        self.assertEqual(product.barcode, "1234567890123")
        self.assertEqual(product.product_brand_id, self.brand)
        self.assertEqual(product.icecat_product_id, "12345")
        self.assertEqual(product.icecat_prod_id, "TEST-MPN-001")
        self.assertIn("Technical specifications", product.public_description or "")
        self.assertTrue(product.sale_ok)

    def test_category_created_and_linked(self):
        product = self._create_from_fixture()
        self.assertEqual(product.icecat_category_id.icecat_id, "555")
        self.assertEqual(product.icecat_category_id.name, "Widgets")
        self.assertEqual(product.categ_id.name, "Widgets")
        self.assertIn(product.icecat_category_id.name, product.public_categ_ids.mapped("name"))

    def test_category_not_created_when_switches_off(self):
        default_categ = self.env.ref("product.product_category_all", raise_if_not_found=False)
        product = self._create_from_fixture(
            create_product_category=False, create_ecommerce_category=False
        )
        # icecat_category_id is still set (classification is always recorded)
        self.assertTrue(product.icecat_category_id)
        self.assertFalse(product.icecat_category_id.product_categ_id)
        self.assertFalse(product.icecat_category_id.ecommerce_categ_id)
        if default_categ:
            self.assertNotEqual(product.categ_id.name, "Widgets")

    def test_main_image_imported(self):
        product = self._create_from_fixture()
        self.assertTrue(product.image_1920)

    def test_gallery_images_deduplicated_against_main(self):
        product = self._create_from_fixture()
        # fixture has 2 gallery pictures, one of which duplicates the main
        # image URL and must not be imported a second time as a
        # product.image record
        self.assertEqual(len(product.product_template_image_ids), 1)

    def test_gallery_images_skipped_when_switch_off(self):
        product = self._create_from_fixture(import_gallery_images=False)
        self.assertFalse(product.product_template_image_ids)

    def test_reusing_same_icecat_category_does_not_duplicate_product_category(self):
        product_1 = self._create_from_fixture(part_number="MPN-1")
        product_2 = self._create_from_fixture(part_number="MPN-2")
        self.assertEqual(product_1.icecat_category_id, product_2.icecat_category_id)
        self.assertEqual(product_1.categ_id, product_2.categ_id)


@tagged("post_install", "-at_install")
class TestIcecatProductImportWizard(BaseCommon):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param("product_icecat.username", "test")
        self.env["ir.config_parameter"].sudo().set_param("product_icecat.password", "test")
        self.manufacturer = self.env["icecat.manufacturer"].create(
            {"name": "Acme", "create_product_category": True}
        )
        self.brand = self.env["product.brand"].create(
            {"name": "Acme Brand", "icecat_manufacturer_id": self.manufacturer.id}
        )

    def test_search_requires_part_number(self):
        wizard = self.env["icecat.product.import"].create({"product_brand_id": self.brand.id})
        with self.assertRaises(UserError):
            wizard.action_search()

    def test_search_requires_brand(self):
        wizard = self.env["icecat.product.import"].create({"part_number": "ABC"})
        with self.assertRaises(UserError):
            wizard.action_search()

    def test_search_requires_brand_with_manufacturer(self):
        brand_without_manufacturer = self.env["product.brand"].create({"name": "No Manufacturer"})
        wizard = self.env["icecat.product.import"].create(
            {"part_number": "ABC", "product_brand_id": brand_without_manufacturer.id}
        )
        with self.assertRaises(UserError):
            wizard.action_search()

    def test_onchange_prefills_from_manufacturer(self):
        wizard = self.env["icecat.product.import"].new({"product_brand_id": self.brand.id})
        wizard._onchange_product_brand_id()
        self.assertTrue(wizard.create_product_category)

    @patch(
        "odoo.addons.product_icecat.models.icecat_api.IcecatClient.get_product_by_part_number"
    )
    def test_search_then_import(self, mock_get_product):
        mock_get_product.return_value = get_test_product()
        wizard = self.env["icecat.product.import"].create(
            {"part_number": "TEST-MPN-001", "product_brand_id": self.brand.id}
        )
        wizard.action_search()
        self.assertEqual(wizard.state, "preview")
        self.assertEqual(wizard.fetched_name, "Acme Widget Pro 15")
        self.assertEqual(wizard.fetched_ean, "1234567890123")

        action = wizard.action_import()
        product = self.env["product.template"].browse(action["res_id"])
        self.assertEqual(product.default_code, "TEST-MPN-001")
        self.assertEqual(product.product_brand_id, self.brand)
