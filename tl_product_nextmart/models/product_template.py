import base64
import hashlib
import logging
from urllib.parse import urlencode, urlparse

import requests
from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools import parse_nextmart_html


_logger = logging.getLogger(__name__)
NEXTMART_DATAVIEW_URL = "https://www.nexmart.com/api/dataview/"
MAX_HTML_SIZE = 10 * 1024 * 1024
MAX_IMAGE_SIZE = 12 * 1024 * 1024


class ProductTemplate(models.Model):
    _inherit = "product.template"

    nextmart_source_url = fields.Char(string="Nextmart URL", copy=False)
    nextmart_last_sync = fields.Datetime(string="Last Nextmart Sync", copy=False)
    nextmart_source_language = fields.Char(string="Nextmart Language", copy=False)
    nextmart_catalog_id = fields.Char(string="Nextmart Catalog ID", copy=False)
    nextmart_supplier_id = fields.Char(string="Nextmart Supplier ID", copy=False)
    nextmart_partner_id = fields.Char(string="Nextmart Partner ID", copy=False)
    nextmart_segment = fields.Char(string="Nextmart Product Segment", copy=False)
    nextmart_marketing_claim = fields.Char(string="Nextmart Marketing Claim", copy=False)
    nextmart_content_hash = fields.Char(string="Nextmart Content Hash", copy=False)
    nextmart_main_image_url = fields.Char(string="Nextmart Main Image URL", copy=False)
    nextmart_specification_ids = fields.One2many(
        comodel_name="product.nextmart.specification",
        inverse_name="product_tmpl_id",
        string="Nextmart Technical Specifications",
        copy=False,
    )
    show_nexmart_data = fields.Boolean(
        string="Show Nextmart DataView on eCommerce",
        copy=False,
        help=(
            "Display the Nextmart DataView iframe on the public eCommerce "
            "product page when the product has a GTIN/EAN and a Partner Key "
            "is configured."
        ),
    )
    nextmart_iframe_url = fields.Char(
        string="Nextmart DataView URL",
        compute="_compute_nextmart_iframe_values",
        compute_sudo=True,
    )
    nextmart_iframe_height = fields.Integer(
        string="Nextmart DataView Height",
        compute="_compute_nextmart_iframe_values",
        compute_sudo=True,
    )

    @api.depends("barcode", "show_nexmart_data")
    @api.depends_context("lang")
    def _compute_nextmart_iframe_values(self):
        config = self._nextmart_config()
        iframe_height = config["iframe_height"]
        website_language = (
            self.env.context.get("lang") or config["language"] or "es"
        ).replace("-", "_").split("_")[0].lower()
        iframe_config = dict(config, language=website_language)
        for product in self:
            product.nextmart_iframe_height = iframe_height
            product.nextmart_iframe_url = False
            if not product.show_nexmart_data or not config["partner_key"]:
                continue
            gtin = product._normalize_gtin(product.barcode)
            if len(gtin) not in (8, 12, 13, 14):
                continue
            product.nextmart_iframe_url = product._build_nextmart_url(
                gtin, iframe_config
            )

    def action_nextmart_enrich(self):
        self.ensure_one()
        if len(self.product_variant_ids) != 1:
            raise UserError(
                _(
                    "This product template has several variants. Open the "
                    "specific variant and run 'Complete with Nextmart' there."
                )
            )
        return self._nextmart_enrich(variant=self.product_variant_id)

    def _nextmart_config(self):
        params = self.env["ir.config_parameter"].sudo()

        def get_bool(key, default=False):
            default_value = "True" if default else "False"
            return str(params.get_param(key, default_value)).lower() in (
                "1",
                "true",
                "yes",
                "on",
            )

        def get_int(key, default):
            try:
                return int(params.get_param(key, str(default)))
            except (TypeError, ValueError):
                return default

        return {
            "partner_key": params.get_param("website.nexmart_apikey"),
            "language": params.get_param("tl_product_nextmart.language", "es"),
            "update_name": get_bool("tl_product_nextmart.update_name", True),
            "overwrite": get_bool(
                "tl_product_nextmart.overwrite_content", False
            ),
            "import_images": get_bool(
                "tl_product_nextmart.import_images", True
            ),
            "import_all_images": get_bool(
                "tl_product_nextmart.import_all_images", True
            ),
            "auto_show_iframe": get_bool(
                "tl_product_nextmart.auto_show_iframe", True
            ),
            "import_specs": get_bool(
                "tl_product_nextmart.import_specifications", True
            ),
            "create_brand_manufacturer": get_bool(
                "tl_product_nextmart.create_brand_manufacturer", True
            ),
            "include_specs_ecommerce": get_bool(
                "tl_product_nextmart.include_specs_ecommerce", True
            ),
            "max_extra_images": max(
                0,
                min(
                    get_int("tl_product_nextmart.max_extra_images", 12),
                    200,
                ),
            ),
            "iframe_height": max(
                500,
                min(
                    get_int("tl_product_nextmart.iframe_height", 1800),
                    5000,
                ),
            ),
            "timeout": max(
                5,
                min(get_int("tl_product_nextmart.timeout", 20), 120),
            ),
        }

    @staticmethod
    def _normalize_gtin(value):
        return "".join(character for character in (value or "") if character.isdigit())

    def _get_nextmart_gtin(self, variant):
        gtin = self._normalize_gtin(variant.barcode or self.barcode)
        if not gtin:
            raise UserError(_("The product does not have an EAN/GTIN barcode."))
        if len(gtin) not in (8, 12, 13, 14):
            raise UserError(
                _(
                    "The barcode '%s' is not a supported GTIN length. Expected "
                    "GTIN-8, UPC-12, EAN-13 or GTIN-14."
                )
                % gtin
            )
        return gtin

    def _build_nextmart_url(self, gtin, config):
        query = urlencode(
            {
                "partnerkey": config["partner_key"],
                "gtin": gtin,
                "lang": config["language"],
            }
        )
        return "%s?%s" % (NEXTMART_DATAVIEW_URL, query)

    def _fetch_nextmart_html(self, url, timeout):
        try:
            response = requests.get(
                url,
                timeout=timeout,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": "Odoo/19 Product Nextmart Enrichment",
                },
            )
            response.raise_for_status()
        except requests.RequestException as error:
            raise UserError(
                _("Nextmart could not be reached: %s") % str(error)
            ) from error

        content = response.content
        if len(content) > MAX_HTML_SIZE:
            raise UserError(_("The Nextmart response is larger than allowed."))
        return content

    @staticmethod
    def _is_allowed_media_url(url):
        parsed = urlparse(url or "")
        hostname = (parsed.hostname or "").lower()
        return (
            parsed.scheme == "https"
            and (hostname == "nexmart.com" or hostname.endswith(".nexmart.com"))
        )

    def _download_nextmart_binary(self, url, timeout, expected_prefix):
        if not self._is_allowed_media_url(url):
            raise UserError(_("Nextmart returned a non-allowed media URL."))
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Odoo/19 Product Nextmart Enrichment"},
        )
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "").lower()
        if expected_prefix and not content_type.startswith(expected_prefix):
            raise UserError(
                _("The downloaded Nextmart resource is not a valid %s file.")
                % expected_prefix.rstrip("/")
            )
        if len(response.content) > MAX_IMAGE_SIZE:
            raise UserError(_("A Nextmart image is larger than allowed."))
        return base64.b64encode(response.content)

    @staticmethod
    def _first(values):
        return values[0] if values else False

    def _prepare_sale_description(self, data):
        parts = []
        if data.get("marketing_claims"):
            parts.append(data["marketing_claims"][0])
        if data.get("description"):
            parts.append(data["description"])
        if data.get("top_features"):
            parts.append(
                "\n".join("• %s" % feature for feature in data["top_features"])
            )
        return "\n\n".join(parts)

    def _prepare_ecommerce_description(self, data, include_specs=True):
        blocks = []
        if data.get("marketing_claims"):
            blocks.append(
                Markup("<p><strong>{}</strong></p>").format(
                    escape(data["marketing_claims"][0])
                )
            )
        if data.get("description"):
            blocks.append(Markup("<p>{}</p>").format(escape(data["description"])))
        if data.get("top_features"):
            items = Markup("").join(
                Markup("<li>{}</li>").format(escape(value))
                for value in data["top_features"]
            )
            blocks.append(
                Markup("<h3>{}</h3><ul>{}</ul>").format(
                    escape(_("Main features")), items
                )
            )
        if data.get("benefits"):
            items = Markup("").join(
                Markup("<li>{}</li>").format(escape(value))
                for value in data["benefits"]
            )
            blocks.append(
                Markup("<h3>{}</h3><ul>{}</ul>").format(
                    escape(_("Product strengths")), items
                )
            )
        if include_specs and data.get("technical_details"):
            rows = Markup("").join(
                Markup("<tr><th>{}</th><td>{}</td></tr>").format(
                    escape(item["name"]), escape(item["value"])
                )
                for item in data["technical_details"]
            )
            blocks.append(
                Markup(
                    "<h3>{}</h3><table class='table table-sm'><tbody>{}</tbody></table>"
                ).format(escape(_("Technical details")), rows)
            )
        return str(Markup("").join(blocks))

    def _find_or_create_brand_manufacturer(self, data, config, warnings):
        brand_data = data.get("brand") or {}
        brand_name = brand_data.get("name")
        analytics = data.get("analytics") or {}
        supplier_id = analytics.get("supplierId")
        catalog_id = analytics.get("catalogId") or ""
        catalog_prefix = catalog_id.split("_")[0] if catalog_id else False

        Brand = self.env["product.brand"].sudo()
        Partner = self.env["res.partner"].sudo()
        brand = Brand

        if supplier_id:
            brand = Brand.search(
                [("nextmart_supplier_id", "=", supplier_id)], limit=1
            )
        if not brand and catalog_prefix:
            brand = Brand.search(
                [("nextmart_catalog_prefix", "=ilike", catalog_prefix)], limit=1
            )
        if not brand and brand_name:
            brand = Brand.search([("name", "=ilike", brand_name)], limit=1)

        manufacturer = brand.partner_id if brand else Partner
        if not manufacturer and brand_name:
            manufacturer = Partner.search(
                [("name", "=ilike", brand_name), ("is_company", "=", True)],
                limit=1,
            )

        if config["create_brand_manufacturer"] and brand_name:
            if not manufacturer:
                partner_values = {
                    "name": brand_name,
                    "is_company": True,
                }
                if "supplier_rank" in Partner._fields:
                    partner_values["supplier_rank"] = 1
                manufacturer = Partner.create(partner_values)

            brand_values = {
                "nextmart_supplier_id": supplier_id,
                "nextmart_catalog_prefix": catalog_prefix,
                "nextmart_logo_url": brand_data.get("logo_url"),
            }
            if not brand:
                brand_values.update(
                    {
                        "name": brand_name,
                        "partner_id": manufacturer.id,
                    }
                )
                brand = Brand.create(brand_values)
            else:
                missing_values = {
                    key: value
                    for key, value in brand_values.items()
                    if value and not brand[key]
                }
                if manufacturer and not brand.partner_id:
                    missing_values["partner_id"] = manufacturer.id
                if missing_values:
                    brand.write(missing_values)

            logo_url = brand_data.get("logo_url")
            if logo_url and (config["overwrite"] or not brand.logo):
                try:
                    brand.logo = self._download_nextmart_binary(
                        logo_url, config["timeout"], "image/"
                    )
                except (requests.RequestException, UserError) as error:
                    warnings.append(_("Brand logo: %s") % str(error))

        return brand, manufacturer

    def _import_images(self, data, config, warnings):
        if not config["import_images"]:
            return 0

        imported = 0
        main_url = data.get("main_image_url")
        main_is_product_image = bool(
            main_url
            and self.image_1920
            and self.nextmart_main_image_url == main_url
        )
        if main_url and (config["overwrite"] or not self.image_1920):
            try:
                self.image_1920 = self._download_nextmart_binary(
                    main_url, config["timeout"], "image/"
                )
                self.nextmart_main_image_url = main_url
                main_is_product_image = True
                imported += 1
            except (requests.RequestException, UserError) as error:
                warnings.append(_("Main image: %s") % str(error))

        ProductImage = self.env["product.image"]
        extra_count = 0
        image_limit = (
            0 if config["import_all_images"] else config["max_extra_images"]
        )
        for image in data.get("images", []):
            if image_limit and extra_count >= image_limit:
                break
            image_url = image.get("url")
            kind = image.get("kind") or _("Nextmart image")
            if not image_url:
                continue
            if image_url == main_url and main_is_product_image:
                continue

            existing = ProductImage.search(
                [
                    ("product_tmpl_id", "=", self.id),
                    ("nextmart_url", "=", image_url),
                ],
                limit=1,
            )
            if existing and not config["overwrite"]:
                extra_count += 1
                continue

            try:
                binary = self._download_nextmart_binary(
                    image_url, config["timeout"], "image/"
                )
            except (requests.RequestException, UserError) as error:
                warnings.append(_("Image %s: %s") % (image_url, str(error)))
                continue

            values = {
                "name": "%s %s" % (kind, extra_count + 1),
                "image_1920": binary,
                "product_tmpl_id": self.id,
                "sequence": image.get("sequence", 10),
                "nextmart_url": image_url,
                "nextmart_kind": kind,
            }
            if existing:
                existing.write(values)
            else:
                ProductImage.create(values)
            extra_count += 1
            imported += 1

        return imported

    def _import_specifications(self, variant, data):
        Specification = self.env["product.nextmart.specification"]
        Specification.search(
            [
                ("product_tmpl_id", "=", self.id),
                ("product_id", "=", variant.id),
            ]
        ).unlink()
        values = [
            Specification._prepare_values(self, variant, item)
            for item in data.get("technical_details", [])
        ]
        if values:
            Specification.create(values)
        return len(values)

    def _nextmart_enrich(self, variant):
        self.ensure_one()
        variant.ensure_one()
        if variant.product_tmpl_id != self:
            raise UserError(_("The selected variant does not belong to this template."))

        config = self._nextmart_config()
        if not config["partner_key"]:
            raise UserError(
                _(
                    "Configure the Nextmart Partner Key in Settings before "
                    "completing products."
                )
            )

        gtin = self._get_nextmart_gtin(variant)
        source_url = self._build_nextmart_url(gtin, config)
        html_content = self._fetch_nextmart_html(source_url, config["timeout"])
        data = parse_nextmart_html(html_content, source_url=source_url)

        if not data.get("name"):
            raise UserError(
                _("Nextmart did not return a product for GTIN %s.") % gtin
            )

        returned_gtin = self._normalize_gtin(data.get("gtin"))
        if returned_gtin and returned_gtin != gtin:
            raise UserError(
                _(
                    "Nextmart returned GTIN %(returned)s instead of the "
                    "requested GTIN %(requested)s. No data was changed."
                )
                % {"returned": returned_gtin, "requested": gtin}
            )

        warnings = []
        analytics = data.get("analytics") or {}
        brand, manufacturer = self._find_or_create_brand_manufacturer(
            data, config, warnings
        )

        template_values = {
            "nextmart_source_url": source_url,
            "nextmart_last_sync": fields.Datetime.now(),
            "nextmart_source_language": config["language"],
            "nextmart_catalog_id": analytics.get("catalogId"),
            "nextmart_supplier_id": analytics.get("supplierId"),
            "nextmart_partner_id": analytics.get("partnerId"),
            "nextmart_segment": data.get("segment"),
            "nextmart_marketing_claim": self._first(
                data.get("marketing_claims", [])
            ),
            "nextmart_content_hash": hashlib.sha256(html_content).hexdigest(),
        }
        if config["auto_show_iframe"]:
            template_values["show_nexmart_data"] = True

        if config["update_name"] and data.get("name"):
            template_values["name"] = data["name"]

        sale_description = self._prepare_sale_description(data)
        if sale_description and (
            config["overwrite"] or not self.description_sale
        ):
            template_values["description_sale"] = sale_description

        ecommerce_description = self._prepare_ecommerce_description(
            data, config["include_specs_ecommerce"]
        )
        if ecommerce_description and (
            config["overwrite"] or not self.description_ecommerce
        ):
            template_values["description_ecommerce"] = ecommerce_description

        if brand and (config["overwrite"] or not self.product_brand_id):
            template_values["product_brand_id"] = brand.id

        self.write(template_values)

        manufacturer_values = {
            "manufacturer_pname": data.get("name"),
            "manufacturer_pref": data.get("manufacturer_reference"),
            "manufacturer_purl": source_url,
        }
        if manufacturer and (config["overwrite"] or not variant.manufacturer_id):
            manufacturer_values["manufacturer_id"] = manufacturer.id
        if not config["overwrite"]:
            manufacturer_values = {
                key: value
                for key, value in manufacturer_values.items()
                if value and (key == "manufacturer_id" or not variant[key])
            }
        if manufacturer_values:
            variant.write(manufacturer_values)

        imported_specs = 0
        if config["import_specs"]:
            imported_specs = self._import_specifications(variant, data)

        imported_images = self._import_images(data, config, warnings)

        _logger.info(
            "Nextmart enrichment completed for product template %s and GTIN %s",
            self.id,
            gtin,
        )

        message = _(
            "Nextmart data imported: %(specs)s specifications and %(images)s images."
        ) % {"specs": imported_specs, "images": imported_images}
        if warnings:
            message += "\n" + _("Warnings: %s") % " | ".join(warnings[:5])

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Nextmart"),
                "message": message,
                "type": "warning" if warnings else "success",
                "sticky": bool(warnings),
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }
