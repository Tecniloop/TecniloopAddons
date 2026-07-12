# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Tests for :mod:`odoo.addons.product_icecat.models.icecat_api`.

These only exercise XML parsing (no HTTP, no database), so a plain
``unittest.TestCase`` is enough — Odoo's test runner discovers and runs it
like any other test class found under ``tests/``.
"""
from unittest import TestCase
from xml.etree import ElementTree as ET

from odoo.addons.product_icecat.models.icecat_api import IcecatProduct

from .common import SAMPLE_PRODUCT_XML, SAMPLE_PRODUCT_XML_ERROR


class TestIcecatProductParsing(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        root = ET.fromstring(SAMPLE_PRODUCT_XML)
        cls.product = IcecatProduct(root.find("Product"))

    def test_identifiers(self):
        self.assertEqual(self.product.icecat_id, "12345")
        self.assertEqual(self.product.prod_id, "TEST-MPN-001")
        self.assertEqual(self.product.title, "Acme Widget Pro 15")
        self.assertEqual(self.product.quality, "ICECAT")

    def test_ean_and_supplier(self):
        self.assertEqual(self.product.ean, "1234567890123")
        self.assertEqual(self.product.supplier_name, "Acme")

    def test_category(self):
        self.assertEqual(self.product.category_icecat_id, "555")
        self.assertEqual(self.product.category_name, "Widgets")

    def test_images(self):
        self.assertEqual(self.product.main_image_url, "https://images.example.com/main.jpg")
        # the gallery includes the main picture too (as real Icecat data
        # does): callers are expected to de-duplicate against
        # main_image_url themselves, they are not filtered out here.
        self.assertEqual(
            self.product.gallery_image_urls,
            [
                "https://images.example.com/main.jpg",
                "https://images.example.com/gallery1.jpg",
            ],
        )

    def test_descriptions(self):
        self.assertIn("15.6 inch", self.product.short_description)
        self.assertEqual(
            self.product.long_description_html, "<b>Premium widget</b> for professionals."
        )

    def test_build_description_html_includes_long_desc_and_specs_table(self):
        html = self.product.build_description_html()
        self.assertIn("<b>Premium widget</b>", html)
        self.assertIn("Technical specifications", html)
        self.assertIn("Display", html)
        self.assertIn("Display diagonal", html)
        self.assertIn("15.6 inch", html)
        self.assertIn("Colour", html)
        self.assertIn("Black", html)

    def test_build_description_html_orders_features_by_priority_desc(self):
        html = self.product.build_description_html()
        # "Display diagonal" (No=100) must appear before "Colour" (No=90)
        self.assertLess(html.index("Display diagonal"), html.index("Colour"))

    def test_error_product_exposes_error_message_attribute(self):
        root = ET.fromstring(SAMPLE_PRODUCT_XML_ERROR)
        product_el = root.find("Product")
        self.assertTrue(product_el.attrib.get("ErrorMessage"))
