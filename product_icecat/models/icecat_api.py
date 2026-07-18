# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Minimal client for the Icecat "XML_s3" real-time product interface.

This intentionally only covers what this module needs: looking up a single
product by manufacturer part number + vendor name, and (optionally)
downloading the full category taxonomy so that locally created Product /
eCommerce categories can keep Icecat's parent/child hierarchy.

It does not attempt to reproduce the bulk daily/full catalog index workflow
(``files.index.xml`` / ``daily.index.xml``) used by tools such as pyIceCat:
that workflow is designed for periodically mirroring the entire catalog,
while this module only ever fetches one product at a time, on demand, so a
much smaller and dependency-free client is enough (only ``requests`` and the
standard library XML parser are used).
"""
import gzip
import io
import logging
from collections import defaultdict
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import requests

from odoo import _

# pylint: disable=prefer-env-translation
# IcecatClient/IcecatProduct are plain Python classes, deliberately usable
# outside of an ORM/request context (see the module docstring and
# IcecatError's docstring below) — there is no `self.env` to call `._()`
# on here. `get_client_from_env()`, which does receive an `env`, uses
# `env._()` as usual.

_logger = logging.getLogger(__name__)

ICECAT_XML_S3_URL = "https://data.icecat.biz/xml_s3/xml_server3.cgi"
ICECAT_CATEGORIES_URL = "https://data.icecat.biz/export/freexml/refs/CategoriesList.xml.gz"
ICECAT_SUPPLIERS_URL = "https://data.icecat.biz/export/freexml/refs/SuppliersList.xml.gz"
ICECAT_CATALOG_BASEURL = "https://data.icecat.biz/export/freexml/EN/"
ICECAT_FULL_INDEX_FILENAME = "files.index.xml"
ICECAT_DAILY_INDEX_FILENAME = "daily.index.xml"

# Icecat's fixed language ID for English in reference/taxonomy files
# (product-detail responses are not affected: they only ever contain the
# single language that was requested via the "lang" parameter).
ICECAT_TAXONOMY_LANGID_EN = "1"

DEFAULT_TIMEOUT = 20
# CategoriesList / SuppliersList reference exports share this timeout: both
# are moderately sized gzipped XML files served from the same refs endpoint.
CATEGORIES_TIMEOUT = 180
SUPPLIERS_TIMEOUT = CATEGORIES_TIMEOUT
CATALOG_INDEX_TIMEOUT = 300
# How many already-processed <file> elements to let the streaming parser
# accumulate under their <files.index> parent before dropping them, to keep
# memory bounded on an index file that can hold millions of entries.
CATALOG_INDEX_GC_EVERY = 500


class IcecatError(Exception):
    """Raised for any Icecat connectivity, authentication or parsing error.

    Deliberately a plain Exception (not an odoo.exceptions.UserError): this
    module is meant to stay usable outside of an ORM/request context too.
    Callers inside Odoo models/wizards should catch it and re-raise as
    UserError with the same message.
    """


class IcecatClient:
    """Thin wrapper around the Icecat XML_s3 real-time interface."""

    def __init__(self, username, password, language="EN", timeout=DEFAULT_TIMEOUT):
        self.username = username
        self.password = password
        self.language = (language or "EN").upper()
        self.timeout = timeout

    # ------------------------------------------------------------------
    # low level HTTP
    # ------------------------------------------------------------------
    def _get(self, params, timeout=None):
        try:
            response = requests.get(
                ICECAT_XML_S3_URL,
                params=params,
                auth=(self.username, self.password),
                timeout=timeout or self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise IcecatError(_("Could not reach Icecat: %s", exc)) from exc

        if response.status_code in (401, 403):
            raise IcecatError(
                _(
                    "Icecat rejected the account credentials (HTTP %s). "
                    "Check the username/password in Settings > General "
                    "Settings > Icecat.",
                    response.status_code,
                )
            )
        if response.status_code == 404:
            raise IcecatError(_("Product not found on Icecat (HTTP 404)."))
        if not 200 <= response.status_code < 300:
            raise IcecatError(
                _("Icecat returned an unexpected error (HTTP %s).", response.status_code)
            )
        return response

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def test_connection(self):
        """Credential check against the real-time product interface.

        Icecat's HTTP status codes alone are not trustworthy here: per
        Icecat's own manual, xml_s3 can answer 200 (with the problem
        reported inside the XML body) or 404 both for "product not found"
        AND for "credentials incorrect / IP not whitelisted". So besides
        the HTTP-level 401/403 handling in :meth:`_get`, the response body
        is parsed and any ErrorMessage other than the expected
        "data-sheet is not present" (normal for the dummy product used
        here) is treated as a failure.
        """
        try:
            response = self._get(
                {"lang": self.language, "prod_id": "0", "vendor": "0", "output": "productxml"}
            )
        except IcecatError as exc:
            if "404" in str(exc):
                # for xml_s3, 404 can also mean bad credentials
                raise IcecatError(
                    _(
                        "Icecat answered HTTP 404 to the connection test. "
                        "Per Icecat's documentation this can mean the "
                        "credentials are incorrect or your server's IP is "
                        "not whitelisted for the account — double-check the "
                        "username (not the e-mail address) and password."
                    )
                ) from exc
            raise
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise IcecatError(_("Icecat returned an invalid XML response: %s", exc)) from exc
        product_el = root.find("Product")
        error_message = product_el.attrib.get("ErrorMessage") if product_el is not None else None
        if error_message and "not present" not in error_message.lower():
            # anything else ("incorrect security data", restricted account,
            # etc.) means the credentials/account are NOT actually usable
            raise IcecatError(
                _("Icecat refused the request: %s", error_message)
            )
        # Real-time access is fine — now also verify the export/reference
        # file access this module's syncs and bulk imports depend on, since
        # Icecat can grant one without the other (see
        # :meth:`_raise_export_auth_error`). Streamed and closed right after
        # the status check, so only headers travel, not the whole file.
        self._check_export_access()
        return True

    def _check_export_access(self):
        """Verify the account can download Icecat's export/reference files
        (checked against ``SuppliersList.xml.gz``), without downloading one."""
        try:
            response = requests.get(
                ICECAT_SUPPLIERS_URL,
                auth=(self.username, self.password),
                stream=True,
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise IcecatError(_("Could not reach Icecat: %s", exc)) from exc
        try:
            if response.status_code in (401, 403):
                self._raise_export_auth_error(response.status_code)
            if not 200 <= response.status_code < 300:
                raise IcecatError(
                    _(
                        "Icecat returned HTTP %s while checking export file access.",
                        response.status_code,
                    )
                )
        finally:
            response.close()
        return True

    def get_product_by_part_number(self, part_number, vendor):
        """Fetch and parse a single product. Returns an :class:`IcecatProduct`."""
        response = self._get(
            {
                "lang": self.language,
                "prod_id": part_number,
                "vendor": vendor,
                "output": "productxml",
            }
        )
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise IcecatError(_("Icecat returned an invalid XML response: %s", exc)) from exc

        product_el = root.find("Product")
        if product_el is None:
            raise IcecatError(_("Unexpected Icecat response: no <Product> element found."))

        error_message = product_el.attrib.get("ErrorMessage")
        if error_message:
            raise IcecatError(error_message)

        return IcecatProduct(product_el)

    def _raise_export_auth_error(self, status_code):
        """Shared 401/403 error for export/index/reference file downloads.

        These files use the same Basic auth as the real-time interface, but
        Icecat only enables them for Open Icecat accounts registered with
        the 'Data (XML)' subscription — 'URL'-type accounts can look up
        single products (so Test Connection may succeed) yet get 401 here.
        """
        raise IcecatError(
            _(
                "Icecat refused access to this export file (HTTP "
                "%(status)s). Export/reference files (SuppliersList, "
                "CategoriesList, catalog indexes) are only available to "
                "Open Icecat accounts with the 'Data (XML)' subscription "
                "— accounts registered for the 'URL' version can look up "
                "single products (so 'Test Connection' succeeds) but are "
                "denied these files. Check your subscription type in your "
                "Icecat account, and verify the username/password in "
                "Settings > General Settings > Icecat.",
                status=status_code,
            )
        )

    def iter_catalog_index_by_supplier(self, supplier_id, full_catalog=True):
        """Stream Icecat's catalog index and yield the ``Prod_ID`` of every
        entry belonging to ``supplier_id``.

        Uses the same ``files.index.xml`` (full catalog) / ``daily.index.xml``
        (recently added/changed only) files as the reference ``pyIceCat``
        client. Unlike the categories reference file, these are served as
        plain (non-gzipped) XML, so no decompression is attempted.

        The whole HTTP response is streamed straight into
        :func:`xml.etree.ElementTree.iterparse` (never buffered fully in
        memory), and already-visited ``<file>`` elements are periodically
        dropped from their ``<files.index>`` parent, since this index can
        hold anywhere from tens of thousands to several million entries for
        the full catalog.
        """
        filename = ICECAT_FULL_INDEX_FILENAME if full_catalog else ICECAT_DAILY_INDEX_FILENAME
        supplier_id = str(supplier_id)
        try:
            response = requests.get(
                ICECAT_CATALOG_BASEURL + filename,
                auth=(self.username, self.password),
                stream=True,
                timeout=CATALOG_INDEX_TIMEOUT,
            )
        except requests.exceptions.RequestException as exc:
            raise IcecatError(
                _("Could not download the Icecat catalog index: %s", exc)
            ) from exc
        if response.status_code in (401, 403):
            self._raise_export_auth_error(response.status_code)
        if not 200 <= response.status_code < 300:
            raise IcecatError(
                _(
                    "Icecat returned HTTP %s while downloading the catalog index.",
                    response.status_code,
                )
            )

        response.raw.decode_content = True
        files_index_el = None
        seen_since_gc = 0
        try:
            for event, elem in ET.iterparse(response.raw, events=("start", "end")):
                if event == "start":
                    if elem.tag == "files.index" and files_index_el is None:
                        files_index_el = elem
                    continue

                if elem.tag != "file":
                    continue
                if elem.attrib.get("Supplier_id") == supplier_id:
                    prod_id = elem.attrib.get("Prod_ID")
                    if prod_id:
                        yield prod_id
                elem.clear()

                seen_since_gc += 1
                if files_index_el is not None and seen_since_gc >= CATALOG_INDEX_GC_EVERY:
                    del files_index_el[:]
                    seen_since_gc = 0
        finally:
            response.close()

    def _download_refs_gzip(self, url, what, timeout):
        """Download one of Icecat's gzipped ``refs`` reference exports and
        return a decompressing file object over its XML content.

        ``what`` is a short human-readable description of the file (already
        translated), used in error messages.
        """
        try:
            response = requests.get(
                url,
                auth=(self.username, self.password),
                timeout=timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise IcecatError(
                _("Could not download the Icecat %(what)s: %(error)s", what=what, error=exc)
            ) from exc
        if response.status_code in (401, 403):
            self._raise_export_auth_error(response.status_code)
        if not 200 <= response.status_code < 300:
            raise IcecatError(
                _(
                    "Icecat returned HTTP %(status)s while downloading the %(what)s.",
                    status=response.status_code,
                    what=what,
                )
            )
        return gzip.GzipFile(fileobj=io.BytesIO(response.content))

    def iter_suppliers(self):
        """Stream Icecat's full suppliers (manufacturers) reference list.

        Downloads ``SuppliersList.xml.gz`` and yields
        ``{"icecat_id": ..., "name": ...}`` dicts, one per ``<Supplier>``
        entry. ``icecat_id`` is Icecat's numeric Supplier ID (the value the
        catalog index files key their ``Supplier_id`` attribute on), and
        ``name`` is the exact spelling Icecat expects as the ``vendor``
        parameter in product lookups.
        """
        with self._download_refs_gzip(
            ICECAT_SUPPLIERS_URL, _("suppliers list"), SUPPLIERS_TIMEOUT
        ) as gz_file:
            for _event, elem in ET.iterparse(gz_file, events=("end",)):
                if elem.tag != "Supplier":
                    continue
                icecat_id = elem.attrib.get("ID")
                name = elem.attrib.get("Name")
                if icecat_id and name:
                    yield {"icecat_id": icecat_id, "name": name.strip()}
                elem.clear()

    def iter_categories(self):
        """Stream the full Icecat category taxonomy.

        Yields ``{"icecat_id": ..., "name": ..., "parent_icecat_id": ...}``
        dicts. Category names are always in English (see
        ``ICECAT_TAXONOMY_LANGID_EN``): this reference file's language
        entries are fixed and independent from the account's configured
        product data language.
        """
        with self._download_refs_gzip(
            ICECAT_CATEGORIES_URL, _("categories list"), CATEGORIES_TIMEOUT
        ) as gz_file:
            for _event, elem in ET.iterparse(gz_file, events=("end",)):
                if elem.tag != "Category":
                    continue
                icecat_id = elem.attrib.get("ID")
                name = None
                for name_el in elem.findall("Name"):
                    if name_el.attrib.get("langid") == ICECAT_TAXONOMY_LANGID_EN:
                        name = name_el.attrib.get("Value")
                        break
                parent_el = elem.find("ParentCategory")
                parent_icecat_id = parent_el.attrib.get("ID") if parent_el is not None else None
                if icecat_id and name:
                    yield {
                        "icecat_id": icecat_id,
                        "name": name,
                        "parent_icecat_id": parent_icecat_id,
                    }
                elem.clear()


class IcecatProduct:
    """Read-only wrapper around a parsed Icecat ``<Product>`` XML element."""

    def __init__(self, product_el):
        self._el = product_el

    # -- identifiers ----------------------------------------------------
    @property
    def icecat_id(self):
        return self._el.attrib.get("ID")

    @property
    def prod_id(self):
        return self._el.attrib.get("Prod_id")

    @property
    def quality(self):
        return self._el.attrib.get("Quality")

    # -- basic descriptive data ------------------------------------------
    @property
    def title(self):
        return self._el.attrib.get("Title") or self._el.attrib.get("Name")

    @property
    def ean(self):
        ean_el = self._el.find("EANCode")
        return ean_el.attrib.get("EAN") if ean_el is not None else False

    @property
    def supplier_name(self):
        supplier_el = self._el.find("Supplier")
        return supplier_el.attrib.get("Name") if supplier_el is not None else False

    # -- category ---------------------------------------------------------
    @property
    def category_icecat_id(self):
        cat_el = self._el.find("Category")
        return cat_el.attrib.get("ID") if cat_el is not None else False

    @property
    def category_name(self):
        cat_el = self._el.find("Category")
        if cat_el is None:
            return False
        name_el = cat_el.find("Name")
        return name_el.attrib.get("Value") if name_el is not None else False

    # -- images -------------------------------------------------------------
    @property
    def main_image_url(self):
        return self._el.attrib.get("HighPic") or None

    @property
    def gallery_image_urls(self):
        urls = []
        gallery_el = self._el.find("ProductGallery")
        if gallery_el is not None:
            for pic_el in gallery_el.findall("ProductPicture"):
                url = pic_el.attrib.get("Pic") or pic_el.attrib.get("Original")
                if url:
                    urls.append(url)
        return urls

    # -- descriptions -------------------------------------------------------
    @property
    def short_description(self):
        summary_el = self._el.find("SummaryDescription")
        if summary_el is not None:
            short_el = summary_el.find("ShortSummaryDescription")
            if short_el is not None and short_el.text:
                return short_el.text
        desc_el = self._el.find("ProductDescription")
        if desc_el is not None and desc_el.attrib.get("ShortDesc"):
            return desc_el.attrib.get("ShortDesc")
        return False

    @property
    def long_description_html(self):
        desc_el = self._el.find("ProductDescription")
        if desc_el is not None and desc_el.attrib.get("LongDesc"):
            # Icecat's LongDesc is already HTML-formatted.
            return desc_el.attrib.get("LongDesc")
        summary_el = self._el.find("SummaryDescription")
        if summary_el is not None:
            long_el = summary_el.find("LongSummaryDescription")
            if long_el is not None and long_el.text:
                return "<p>%s</p>" % escape(long_el.text)
        return ""

    def _feature_group_names(self):
        """Map CategoryFeatureGroup instance ID -> (display name, priority)."""
        names, priorities = {}, {}
        for group_el in self._el.findall("CategoryFeatureGroup"):
            group_id = group_el.attrib.get("ID")
            feature_group_el = group_el.find("FeatureGroup")
            name_el = feature_group_el.find("Name") if feature_group_el is not None else None
            names[group_id] = (
                name_el.attrib.get("Value") if name_el is not None else str(_("Other"))
            )
            try:
                priorities[group_id] = int(group_el.attrib.get("No", "0"))
            except ValueError:
                priorities[group_id] = 0
        return names, priorities

    def build_description_html(self):
        """Long description followed by a technical specifications table.

        Suitable for the OCA ``website_sale_product_description`` module's
        ``public_description`` field: this is the "extended description with
        characteristics" requested for the Icecat integration.
        """
        parts = []
        long_desc = self.long_description_html
        if long_desc:
            parts.append(long_desc)

        group_names, group_priorities = self._feature_group_names()
        grouped_features = defaultdict(list)
        for feature_el in self._el.findall("ProductFeature"):
            group_id = feature_el.attrib.get("CategoryFeatureGroup_ID")
            feature_child = feature_el.find("Feature")
            name_el = feature_child.find("Name") if feature_child is not None else None
            feature_name = name_el.attrib.get("Value") if name_el is not None else None
            value = feature_el.attrib.get("Presentation_Value") or feature_el.attrib.get("Value")
            if feature_name and value:
                try:
                    priority = int(feature_el.attrib.get("No", "0"))
                except ValueError:
                    priority = 0
                grouped_features[group_id].append((priority, feature_name, value))

        if grouped_features:
            parts.append("<h3>%s</h3>" % escape(str(_("Technical specifications"))))
            ordered_group_ids = sorted(
                grouped_features.keys(),
                key=lambda gid: group_priorities.get(gid, 0),
                reverse=True,
            )
            for group_id in ordered_group_ids:
                group_name = group_names.get(group_id, str(_("Other")))
                rows = sorted(grouped_features[group_id], key=lambda row: row[0], reverse=True)
                parts.append("<h4>%s</h4>" % escape(group_name))
                parts.append('<table class="table table-sm table-striped">')
                for _priority, feature_name, value in rows:
                    parts.append(
                        "<tr><td>%s</td><td>%s</td></tr>" % (escape(feature_name), escape(value))
                    )
                parts.append("</table>")

        return "".join(parts)


def get_client_from_env(env):
    """Build an :class:`IcecatClient` from the ``product_icecat.*`` system parameters."""
    icp = env["ir.config_parameter"].sudo()
    # .strip() guards against a stray space/newline pasted into Settings —
    # a silent way to get "Login or password are invalid" from Icecat.
    username = (icp.get_param("product_icecat.username") or "").strip()
    password = (icp.get_param("product_icecat.password") or "").strip()
    language = icp.get_param("product_icecat.language", default="EN")
    if not username or not password:
        raise IcecatError(
            env._(
                "The Icecat account is not configured. Go to Settings > "
                "General Settings > Icecat and enter your credentials first."
            )
        )
    return IcecatClient(username=username, password=password, language=language)
