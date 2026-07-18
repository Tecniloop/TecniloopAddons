# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Tests for :mod:`odoo.addons.product_icecat.models.icecat_api`.

These only exercise XML parsing (no HTTP, no database), so a plain
``unittest.TestCase`` is enough — Odoo's test runner discovers and runs it
like any other test class found under ``tests/``.
"""
from datetime import date
from io import BytesIO
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


class TestIcecatSuppliersParsing(TestCase):
    """``iter_suppliers`` with the HTTP layer mocked out: only download +
    gzip + XML handling is exercised, mirroring how Icecat actually serves
    ``SuppliersList.xml.gz``."""

    def _iter_suppliers(self, status_code=200, content=None):
        from unittest.mock import MagicMock, patch

        from odoo.addons.product_icecat.models.icecat_api import IcecatClient

        from .common import SAMPLE_SUPPLIERS_XML, gzip_bytes

        response = MagicMock()
        response.status_code = status_code
        response.content = gzip_bytes(content if content is not None else SAMPLE_SUPPLIERS_XML)
        client = IcecatClient(username="user", password="secret")
        with patch(
            "odoo.addons.product_icecat.models.icecat_api.requests.get",
            return_value=response,
        ) as mocked_get:
            rows = list(client.iter_suppliers())
        return rows, mocked_get

    def test_iter_suppliers_yields_id_and_stripped_name(self):
        rows, mocked_get = self._iter_suppliers()
        self.assertEqual(
            rows,
            [
                {"icecat_id": "1", "name": "HP"},
                {"icecat_id": "99", "name": "Acme"},
                {"icecat_id": "734", "name": "Lenovo"},
            ],
        )
        # entries missing an ID or a Name are skipped, not crashed on
        self.assertNotIn("No ID, skipped", [row["name"] for row in rows])
        called_url = mocked_get.call_args[0][0]
        self.assertEqual(
            called_url, "https://data.icecat.biz/export/freexml/refs/SuppliersList.xml.gz"
        )

    def test_iter_suppliers_raises_on_bad_credentials(self):
        from odoo.addons.product_icecat.models.icecat_api import IcecatError

        with self.assertRaises(IcecatError):
            self._iter_suppliers(status_code=401)


class TestIcecatCatalogIndexParsing(TestCase):
    def _iter_index(self, **kwargs):
        from unittest.mock import MagicMock, patch

        from odoo.addons.product_icecat.models.icecat_api import IcecatClient

        from .common import SAMPLE_INDEX_XML, gzip_bytes

        response = MagicMock()
        response.status_code = 200
        response.raw = BytesIO(gzip_bytes(SAMPLE_INDEX_XML))
        client = IcecatClient(username="user", password="secret")
        with patch(
            "odoo.addons.product_icecat.models.icecat_api.requests.get",
            return_value=response,
        ) as mocked_get:
            rows = list(client.iter_catalog_index_by_supplier("99", **kwargs))
        return rows, mocked_get

    def test_on_market_index_is_default_and_filtered_by_supplier(self):
        rows, mocked_get = self._iter_index()
        self.assertEqual(rows, ["ACME-OLD", "ACME-NEW", "NO-DATE"])
        called_url = mocked_get.call_args[0][0]
        self.assertEqual(
            called_url,
            "https://data.icecat.biz/export/freexml/EN/on_market.index.xml.gz",
        )

    def test_on_market_index_uses_configured_language_market(self):
        from unittest.mock import MagicMock, patch

        from odoo.addons.product_icecat.models.icecat_api import IcecatClient

        from .common import SAMPLE_INDEX_XML, gzip_bytes

        response = MagicMock()
        response.status_code = 200
        response.raw = BytesIO(gzip_bytes(SAMPLE_INDEX_XML))
        client = IcecatClient(username="user", password="secret", language="ES")
        with patch(
            "odoo.addons.product_icecat.models.icecat_api.requests.get",
            return_value=response,
        ) as mocked_get:
            list(client.iter_catalog_index_by_supplier("99"))
        self.assertEqual(
            mocked_get.call_args[0][0],
            "https://data.icecat.biz/export/freexml/ES/on_market.index.xml.gz",
        )

    def test_modified_since_filters_old_and_undated_entries(self):
        rows, _mocked_get = self._iter_index(modified_since=date(2026, 1, 1))
        self.assertEqual(rows, ["ACME-NEW"])

    def test_full_and_daily_index_names(self):
        _rows, mocked_get = self._iter_index(index_type="full")
        self.assertTrue(mocked_get.call_args[0][0].endswith("/files.index.xml.gz"))

        _rows, mocked_get = self._iter_index(index_type="daily")
        self.assertTrue(mocked_get.call_args[0][0].endswith("/daily.index.xml.gz"))
