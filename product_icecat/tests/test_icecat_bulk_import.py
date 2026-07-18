# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import date
from unittest.mock import patch

from odoo.addons.base.tests.common import BaseCommon
from odoo.tests import tagged

from ..models.icecat_api import IcecatError
from .common import get_test_product


@tagged("post_install", "-at_install")
class TestIcecatBulkScan(BaseCommon):
    def setUp(self):
        super().setUp()
        self.manufacturer = self.env["icecat.manufacturer"].create(
            {"name": "Acme", "icecat_supplier_id": "99"}
        )
        self.brand = self.env["product.brand"].create(
            {"name": "Acme Brand", "icecat_manufacturer_id": self.manufacturer.id}
        )

    @patch(
        "odoo.addons.product_icecat.models.icecat_api.IcecatClient."
        "iter_catalog_index_by_supplier"
    )
    def test_scan_creates_pending_lines(self, mock_iter):
        mock_iter.return_value = iter(["MPN-1", "MPN-2", "MPN-3"])
        self.brand._icecat_bulk_scan()

        self.assertEqual(self.brand.icecat_bulk_state, "importing")
        self.assertEqual(self.brand.icecat_bulk_total, 3)
        lines = self.brand.icecat_import_line_ids
        self.assertEqual(len(lines), 3)
        self.assertEqual(set(lines.mapped("part_number")), {"MPN-1", "MPN-2", "MPN-3"})
        self.assertTrue(all(line.state == "pending" for line in lines))

    @patch(
        "odoo.addons.product_icecat.models.icecat_api.IcecatClient."
        "iter_catalog_index_by_supplier"
    )
    def test_scan_marks_already_imported_products_as_skipped(self, mock_iter):
        mock_iter.return_value = iter(["MPN-1", "MPN-2"])
        self.env["product.template"].create(
            {
                "name": "Already Here",
                "product_brand_id": self.brand.id,
                "icecat_prod_id": "MPN-1",
            }
        )
        self.brand._icecat_bulk_scan()

        lines = {line.part_number: line.state for line in self.brand.icecat_import_line_ids}
        self.assertEqual(lines["MPN-1"], "skipped")
        self.assertEqual(lines["MPN-2"], "pending")

    @patch(
        "odoo.addons.product_icecat.models.icecat_api.IcecatClient."
        "iter_catalog_index_by_supplier"
    )
    def test_rescanning_does_not_duplicate_lines(self, mock_iter):
        mock_iter.return_value = iter(["MPN-1", "MPN-2"])
        self.brand._icecat_bulk_scan()
        mock_iter.return_value = iter(["MPN-1", "MPN-2", "MPN-3"])
        self.brand._icecat_bulk_scan()

        self.assertEqual(len(self.brand.icecat_import_line_ids), 3)

    @patch(
        "odoo.addons.product_icecat.models.icecat_api.IcecatClient."
        "iter_catalog_index_by_supplier"
    )
    def test_scan_respects_limit(self, mock_iter):
        mock_iter.return_value = iter(["MPN-1", "MPN-2", "MPN-3"])
        self.brand.icecat_bulk_limit = 2
        self.brand._icecat_bulk_scan()
        self.assertEqual(self.brand.icecat_bulk_total, 2)
        self.assertEqual(len(self.brand.icecat_import_line_ids), 2)

    @patch(
        "odoo.addons.product_icecat.models.icecat_api.IcecatClient."
        "iter_catalog_index_by_supplier"
    )
    def test_scan_passes_index_and_modified_since_filters(self, mock_iter):
        mock_iter.return_value = iter([])
        self.brand.write(
            {
                "icecat_bulk_index_type": "on_market",
                "icecat_bulk_modified_since": date(2026, 1, 1),
            }
        )
        self.brand._icecat_bulk_scan()
        mock_iter.assert_called_once_with(
            "99",
            index_type="on_market",
            modified_since=date(2026, 1, 1),
            added_since=False,
            category_ids=set(),
            quality_mode="described",
            only_on_market=True,
            only_with_image=False,
            only_unrestricted=True,
        )

    @patch(
        "odoo.addons.product_icecat.models.icecat_api.IcecatClient."
        "iter_catalog_index_by_supplier"
    )
    def test_scan_expands_selected_category_to_children(self, mock_iter):
        parent = self.env["icecat.category"].create(
            {"name": "Parent", "icecat_id": "10"}
        )
        self.env["icecat.category"].create(
            {"name": "Child", "icecat_id": "11", "parent_id": parent.id}
        )
        self.brand.icecat_bulk_category_ids = parent
        mock_iter.return_value = iter([])

        self.brand._icecat_bulk_scan()

        self.assertEqual(mock_iter.call_args.kwargs["category_ids"], {"10", "11"})


@tagged("post_install", "-at_install")
class TestIcecatImportLine(BaseCommon):
    def setUp(self):
        super().setUp()
        self.manufacturer = self.env["icecat.manufacturer"].create({"name": "Acme"})
        self.brand = self.env["product.brand"].create(
            {"name": "Acme Brand", "icecat_manufacturer_id": self.manufacturer.id}
        )

    def test_unique_part_number_per_brand(self):
        self.env["icecat.import.line"].create(
            {
                "product_brand_id": self.brand.id,
                "icecat_manufacturer_id": self.manufacturer.id,
                "part_number": "MPN-1",
            }
        )
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env["icecat.import.line"].create(
                    {
                        "product_brand_id": self.brand.id,
                        "icecat_manufacturer_id": self.manufacturer.id,
                        "part_number": "MPN-1",
                    }
                )

    @patch(
        "odoo.addons.product_icecat.models.icecat_api.IcecatClient.get_product_by_part_number"
    )
    def test_process_success(self, mock_get_product):
        mock_get_product.return_value = get_test_product()
        line = self.env["icecat.import.line"].create(
            {
                "product_brand_id": self.brand.id,
                "icecat_manufacturer_id": self.manufacturer.id,
                "part_number": "TEST-MPN-001",
            }
        )
        line._process()
        self.assertEqual(line.state, "done")
        self.assertTrue(line.product_id)
        self.assertEqual(line.product_id.default_code, "TEST-MPN-001")

    @patch(
        "odoo.addons.product_icecat.models.icecat_api.IcecatClient.get_product_by_part_number"
    )
    def test_process_failure_is_recorded_on_the_line(self, mock_get_product):
        mock_get_product.side_effect = IcecatError("Product not found on Icecat (HTTP 404).")
        line = self.env["icecat.import.line"].create(
            {
                "product_brand_id": self.brand.id,
                "icecat_manufacturer_id": self.manufacturer.id,
                "part_number": "MISSING-MPN",
            }
        )
        line._process()
        self.assertEqual(line.state, "error")
        self.assertIn("not found", line.error_message)

    def test_action_retry_requires_error_lines(self):
        line = self.env["icecat.import.line"].create(
            {
                "product_brand_id": self.brand.id,
                "icecat_manufacturer_id": self.manufacturer.id,
                "part_number": "MPN-1",
            }
        )
        with self.assertRaises(Exception):
            line.action_retry()


@tagged("post_install", "-at_install")
class TestIcecatBulkImportCron(BaseCommon):
    """Exercises _cron_process_icecat_bulk_import(), which commits the
    transaction as it goes (see the comment on that method). cr.commit is
    mocked out here so the test keeps its usual rollback-based isolation.
    """

    def setUp(self):
        super().setUp()
        self.manufacturer = self.env["icecat.manufacturer"].create(
            {"name": "Acme", "icecat_supplier_id": "99"}
        )
        self.brand = self.env["product.brand"].create(
            {"name": "Acme Brand", "icecat_manufacturer_id": self.manufacturer.id}
        )

    @patch(
        "odoo.addons.product_icecat.models.icecat_api.IcecatClient.get_product_by_part_number"
    )
    @patch(
        "odoo.addons.product_icecat.models.icecat_api.IcecatClient."
        "iter_catalog_index_by_supplier"
    )
    def test_full_cycle_scan_then_import_then_done(self, mock_iter, mock_get_product):
        mock_iter.return_value = iter(["TEST-MPN-001"])
        mock_get_product.return_value = get_test_product()
        self.brand.icecat_bulk_state = "scanning"

        with patch.object(self.env.cr, "commit"):
            # a single tick both scans (queuing the one match) and, since
            # it fits well under BULK_IMPORT_BATCH_SIZE, processes it and
            # closes the brand out in the same call.
            self.env["product.brand"]._cron_process_icecat_bulk_import()

        self.assertEqual(len(self.brand.icecat_import_line_ids), 1)
        self.assertEqual(self.brand.icecat_bulk_state, "done")
        line = self.brand.icecat_import_line_ids
        self.assertEqual(line.state, "done")
        self.assertTrue(line.product_id)
        self.assertEqual(line.product_id.default_code, "TEST-MPN-001")

    @patch(
        "odoo.addons.product_icecat.models.icecat_api.IcecatClient."
        "iter_catalog_index_by_supplier"
    )
    def test_scan_failure_sets_brand_error_state(self, mock_iter):
        mock_iter.side_effect = IcecatError("Icecat rejected the account credentials (HTTP 401).")
        self.brand.icecat_bulk_state = "scanning"

        with patch.object(self.env.cr, "commit"):
            self.env["product.brand"]._cron_process_icecat_bulk_import()

        self.assertEqual(self.brand.icecat_bulk_state, "error")
        self.assertIn("401", self.brand.icecat_bulk_error_message)

    def test_brand_with_nothing_pending_is_closed_out(self):
        # every match already existed as a product -> scan marks it
        # "skipped", so the brand should be closed out on the same tick
        # instead of waiting on a batch that will never come
        self.env["product.template"].create(
            {
                "name": "Already Here",
                "product_brand_id": self.brand.id,
                "icecat_prod_id": "MPN-1",
            }
        )
        with patch(
            "odoo.addons.product_icecat.models.icecat_api.IcecatClient."
            "iter_catalog_index_by_supplier",
            return_value=iter(["MPN-1"]),
        ):
            self.brand.icecat_bulk_state = "scanning"
            with patch.object(self.env.cr, "commit"):
                self.env["product.brand"]._cron_process_icecat_bulk_import()

        self.assertEqual(self.brand.icecat_bulk_state, "done")
        self.assertEqual(self.brand.icecat_import_line_ids.state, "skipped")
