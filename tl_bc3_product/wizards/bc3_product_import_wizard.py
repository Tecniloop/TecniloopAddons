import base64
import html
import io
import os
import posixpath
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from odoo import _, fields, models
from odoo.exceptions import UserError


IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
EXECUTABLE_EXTENSIONS = {".exe", ".dll", ".bat", ".cmd", ".com", ".msi", ".ps1", ".sh"}


def b64(payload):
    return base64.b64encode(payload or b"")


def clean(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return "".join(ch for ch in value if ch in ("\t", "\n", "\r") or ord(ch) >= 32).strip()


class MediaZipReader:
    def __init__(self, payload):
        self.payload = payload or b""
        self.by_path = {}
        self.by_base = {}
        if self.payload:
            self._load()

    def _normalize(self, name):
        name = clean(name).replace("\\", "/")
        if not name or "\x00" in name:
            raise UserError(_("Invalid file name in media ZIP."))
        if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
            raise UserError(_("Absolute paths are not allowed in media ZIP."))
        normalized = posixpath.normpath(name)
        if normalized in (".", "..") or normalized.startswith("../"):
            raise UserError(_("Path traversal is not allowed in media ZIP."))
        return normalized

    def _load(self):
        try:
            archive = zipfile.ZipFile(io.BytesIO(self.payload))
        except zipfile.BadZipFile as exc:
            raise UserError(_("Invalid media ZIP file: %s") % exc)
        total_size = 0
        for info in archive.infolist():
            if info.is_dir():
                continue
            normalized = self._normalize(info.filename)
            total_size += info.file_size
            if info.file_size > 75 * 1024 * 1024:
                raise UserError(_("Media ZIP contains a file larger than 75 MB: %s") % normalized)
            if total_size > 500 * 1024 * 1024:
                raise UserError(_("Media ZIP uncompressed size is larger than 500 MB."))
            self.by_path[normalized.lower()] = (archive, info, normalized)
            self.by_base.setdefault(posixpath.basename(normalized).lower(), (archive, info, normalized))

    def read(self, filename):
        filename = clean(filename).replace("\\", "/").lstrip("./")
        if not filename:
            return None, None
        key = posixpath.normpath(filename).lower()
        base = posixpath.basename(filename).lower()
        item = self.by_path.get(key) or self.by_base.get(base)
        if not item:
            return None, None
        archive, info, normalized = item
        ext = posixpath.splitext(normalized.lower())[1]
        if ext in EXECUTABLE_EXTENSIONS:
            return normalized, None
        return normalized, archive.read(info)


class MediaRelatedReader:
    def __init__(self, wizard, batch=None):
        self.wizard = wizard
        self.batch = batch
        zip_payload = b""
        if batch and batch.media_zip_file:
            zip_payload = base64.b64decode(batch.media_zip_file or b"")
        elif wizard.media_zip_file:
            zip_payload = base64.b64decode(wizard.media_zip_file or b"")
        self.zip_reader = MediaZipReader(zip_payload) if zip_payload else MediaZipReader(b"")
        self.source_archive_reader = None
        self.source_archive_checked = False

    def read(self, media):
        filename, payload = self.zip_reader.read(media.filename)
        if payload:
            return filename, payload
        filename, payload = self._read_from_server_path(media)
        if payload:
            return filename, payload
        filename, payload = self._read_from_source_archive(media)
        if payload:
            return filename, payload
        return self._read_from_url(media)


    def _read_from_source_archive(self, media):
        archive_reader = self._get_source_archive_reader()
        if not archive_reader:
            return None, None
        return archive_reader.read(media.filename)

    def _get_source_archive_reader(self):
        if self.source_archive_checked:
            return self.source_archive_reader
        self.source_archive_checked = True
        file_rec = self.wizard.file_id
        if not file_rec.source_url:
            return None
        filename = posixpath.basename(urllib.parse.urlparse(file_rec.source_url).path or "").lower()
        if not filename.endswith(".zip"):
            return None
        payload, _downloaded_name = file_rec._download_url(file_rec.source_url, required=False)
        if not payload:
            return None
        try:
            self.source_archive_reader = MediaZipReader(payload)
        except Exception:
            self.source_archive_reader = None
        return self.source_archive_reader

    def _read_from_server_path(self, media):
        base_path = clean((self.batch and self.batch.media_server_path) or self.wizard.media_server_path)
        if not base_path:
            file_rec = self.wizard.file_id
            if file_rec.source_type == "server_path" and file_rec.server_path:
                base_path = os.path.dirname(file_rec.server_path)
        if not base_path:
            return None, None
        filename = clean(media.filename).replace("\\", "/").lstrip("/")
        if not filename:
            return None, None
        candidate = os.path.normpath(os.path.join(base_path, filename))
        base_real = os.path.realpath(base_path)
        candidate_real = os.path.realpath(candidate)
        if not candidate_real.startswith(base_real):
            return None, None
        if not os.path.isfile(candidate_real):
            candidate_real = os.path.join(base_real, os.path.basename(filename))
        if not os.path.isfile(candidate_real):
            return None, None
        if os.path.splitext(candidate_real.lower())[1] in EXECUTABLE_EXTENSIONS:
            return os.path.basename(candidate_real), None
        with open(candidate_real, "rb") as handler:
            return os.path.basename(candidate_real), handler.read()

    def _read_from_url(self, media):
        file_rec = self.wizard.file_id
        for url in self._candidate_urls(file_rec, media):
            filename, payload = self._download_url(file_rec, url)
            if payload:
                return filename, payload
        return None, None

    def _candidate_urls(self, file_rec, media):
        filename = clean(media.filename).replace("\\", "/")
        if not filename:
            return []
        parsed = urllib.parse.urlparse(filename)
        if parsed.scheme in ("http", "https"):
            return [filename]
        candidates = []
        bases = []
        if file_rec.url_base:
            bases.append(self._as_directory_url(file_rec.url_base))
        if file_rec.source_url:
            bases.append(self._as_directory_url(file_rec.source_url))
        url_ext = clean(media.url_ext).replace("\\", "/")
        if url_ext:
            ext_parsed = urllib.parse.urlparse(url_ext)
            if ext_parsed.scheme in ("http", "https"):
                candidates.append(urllib.parse.urljoin(self._as_directory_url(url_ext), filename))
            else:
                for base in bases:
                    if base:
                        candidates.append(urllib.parse.urljoin(urllib.parse.urljoin(base, url_ext.rstrip("/") + "/"), filename))
        for base in bases:
            if base:
                candidates.append(urllib.parse.urljoin(base, filename.lstrip("/")))
        result = []
        seen = set()
        for url in candidates:
            if url and url not in seen:
                result.append(url)
                seen.add(url)
        return result

    def _as_directory_url(self, url):
        if not url:
            return ""
        parsed = urllib.parse.urlparse(url)
        if not parsed.scheme:
            return ""
        if url.endswith("/"):
            return url
        path = parsed.path or "/"
        if posixpath.basename(path) and "." in posixpath.basename(path):
            path = posixpath.dirname(path.rstrip("/")) + "/"
        elif not path.endswith("/"):
            path += "/"
        return urllib.parse.urlunparse(parsed._replace(path=path, params="", query="", fragment=""))

    def _download_url(self, file_rec, url):
        parsed = urllib.parse.urlparse(url or "")
        filename = posixpath.basename(urllib.parse.unquote(parsed.path)) or posixpath.basename(clean(url))
        if parsed.scheme not in ("http", "https"):
            return filename, None
        max_size = int(self.wizard.max_related_file_size_mb or 75) * 1024 * 1024
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Odoo-BC3-Importer/1.0"})
            context = ssl._create_unverified_context() if file_rec.allow_insecure_ssl else ssl.create_default_context()
            with urllib.request.urlopen(request, timeout=30, context=context) as response:
                length = response.headers.get("Content-Length")
                if length and int(length) > max_size:
                    return filename, None
                chunks = []
                total = 0
                while True:
                    chunk = response.read(1024 * 512)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_size:
                        return filename, None
                    chunks.append(chunk)
                return filename, b"".join(chunks)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ssl.SSLError, ValueError):
            return filename, None


class Bc3ProductImportWizard(models.TransientModel):
    _name = "bc3.product.import.wizard"
    _description = "Import BC3 Products"

    file_id = fields.Many2one("bc3.file", required=True, domain=[("state", "=", "parsed")])
    brand_id = fields.Many2one("res.brand", string="Brand")
    brand_name = fields.Char(string="Brand / Manufacturer")
    create_brand = fields.Boolean(default=True)
    create_website_categories = fields.Boolean(default=True)
    website_parent_categ_id = fields.Many2one("product.public.category", string="Parent Website Category")
    replace_website_categories = fields.Boolean(string="Replace Existing Website Categories")
    import_work_units = fields.Boolean(default=True)
    import_resources = fields.Boolean(default=True)
    import_other = fields.Boolean(default=True)
    include_zero_price = fields.Boolean(default=True)
    update_existing = fields.Boolean(default=True)
    publish_on_website = fields.Boolean()
    default_product_type = fields.Selection([("consu", "Goods"), ("service", "Service")], default="consu", required=True)
    track_inventory = fields.Boolean(default=True)
    import_images = fields.Boolean(default=True)
    set_first_image = fields.Boolean(default=True)
    overwrite_image = fields.Boolean()
    media_zip_file = fields.Binary(string="Media ZIP", attachment=True)
    media_zip_filename = fields.Char()
    media_server_path = fields.Char(string="Media Server Path")
    max_related_file_size_mb = fields.Integer(default=75)
    batch_size = fields.Integer(default=200, required=True)
    process_first_chunk = fields.Boolean(default=True)
    preview_html = fields.Html(readonly=True)

    def action_preview(self):
        self.ensure_one()
        concepts = self._get_importable_concepts()
        rows = []
        for concept in concepts[:80]:
            rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                html.escape(concept.code or ""),
                html.escape(concept.category or ""),
                html.escape(concept.unit_name or ""),
                html.escape(concept.name or ""),
                len(concept.media_ref_ids.filtered("is_image")),
            ))
        self.preview_html = """
            <p><b>BC3:</b> %s<br/><b>Brand:</b> %s<br/><b>Importable products:</b> %s</p>
            <table class="table table-sm table-hover">
                <thead><tr><th>Code</th><th>Category</th><th>UoM</th><th>Name</th><th>Images</th></tr></thead>
                <tbody>%s</tbody>
            </table>
        """ % (html.escape(self.file_id.display_name), html.escape(self.brand_name or self.brand_id.display_name or ""), len(concepts), "".join(rows))
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form", "target": "new"}

    def action_import(self):
        self.ensure_one()
        batch = self._create_import_batch(process_first_chunk=self.process_first_chunk)
        return {"type": "ir.actions.act_window", "name": _("BC3 Product Import"), "res_model": "bc3.product.import.batch", "view_mode": "form", "res_id": batch.id}

    def _create_import_batch(self, process_first_chunk=True, manufacturer=None):
        self.ensure_one()
        if self.file_id.state != "parsed":
            raise UserError(_("Parse the BC3 file before importing products."))
        brand = self._get_or_create_brand()
        concepts = self._get_importable_concepts()
        batch = self.env["bc3.product.import.batch"].sudo().create({
            "name": _("BC3 product import - %s") % self.file_id.display_name,
            "file_id": self.file_id.id,
            "manufacturer_id": manufacturer.id if manufacturer else False,
            "brand_id": brand.id if brand else False,
            "state": "queued" if concepts else "done",
            "started_at": fields.Datetime.now(),
            "total_concepts": len(concepts),
            "batch_size": self.batch_size or 200,
            "create_website_categories": self.create_website_categories,
            "website_parent_categ_id": self.website_parent_categ_id.id if self.website_parent_categ_id else False,
            "replace_website_categories": self.replace_website_categories,
            "include_zero_price": self.include_zero_price,
            "update_existing": self.update_existing,
            "publish_on_website": self.publish_on_website,
            "default_product_type": self.default_product_type,
            "track_inventory": self.track_inventory,
            "import_images": self.import_images,
            "set_first_image": self.set_first_image,
            "overwrite_image": self.overwrite_image,
            "media_zip_file": self.media_zip_file,
            "media_zip_filename": self.media_zip_filename,
            "media_server_path": self.media_server_path,
            "max_related_file_size_mb": self.max_related_file_size_mb,
        })
        self._stage_lines(batch, concepts)
        if process_first_chunk and concepts:
            batch._process_next_chunk(limit=batch.batch_size)
        return batch

    def _stage_lines(self, batch, concepts):
        Line = self.env["bc3.product.import.line"].sudo()
        vals_list = []
        for sequence, concept in enumerate(concepts, start=1):
            vals_list.append({"batch_id": batch.id, "sequence": sequence, "concept_id": concept.id, "state": "pending"})
            if len(vals_list) >= 500:
                Line.create(vals_list)
                vals_list = []
        if vals_list:
            Line.create(vals_list)

    def _get_importable_concepts(self):
        self.ensure_one()
        concepts = self.file_id.concept_ids.filtered(lambda c: c.category not in ("root", "chapter", "percentage"))
        if not self.import_work_units:
            concepts = concepts.filtered(lambda c: c.category != "work_unit")
        if not self.import_resources:
            concepts = concepts.filtered(lambda c: c.category != "resource")
        if not self.import_other:
            concepts = concepts.filtered(lambda c: c.category != "other")
        if not self.include_zero_price:
            concepts = concepts.filtered(lambda c: c.price_unit)
        return concepts.sorted(key=lambda c: (c.code or "", c.id))

    def _get_or_create_brand(self):
        self.ensure_one()
        if self.brand_id:
            return self.brand_id
        brand_name = clean(self.brand_name or self.file_id.property_file or self.file_id.name or self.file_id.filename)
        if not brand_name:
            raise UserError(_("Please select a brand or enter a brand/manufacturer name."))
        Brand = self.env["res.brand"].sudo()
        brand = Brand.search([("name", "=", brand_name)], limit=1)
        if brand:
            return brand
        if not self.create_brand:
            raise UserError(_("Brand '%s' does not exist and automatic creation is disabled.") % brand_name)
        partner = self.env["res.partner"].sudo().create({"name": brand_name, "company_type": "company"})
        return Brand.create({"partner_id": partner.id})

    def _create_or_update_product(self, concept, brand):
        Product = self.env["product.template"].sudo()
        domain = ["|", ("bc3_concept_id", "=", concept.id), ("bc3_code", "=", concept.code)]
        product = Product.search(domain, limit=1)
        if not product:
            product = Product.search([("default_code", "=", concept.code)], limit=1)
        if product and not self.update_existing:
            return False, False
        vals = self._product_values(concept, brand)
        if product:
            product.write(vals)
            concept.sudo().write({"product_tmpl_id": product.id})
            return product, False
        product = Product.create(vals)
        concept.sudo().write({"product_tmpl_id": product.id})
        return product, True

    def _product_values(self, concept, brand):
        uom = self._map_uom(concept.unit_name)
        vals = {
            "name": concept.name or concept.code,
            "default_code": concept.code,
            "list_price": concept.price_unit,
            "bc3_is_imported": True,
            "bc3_file_id": concept.file_id.id,
            "bc3_concept_id": concept.id,
            "bc3_code": concept.code,
            "bc3_normalized_code": concept.normalized_code,
            "bc3_alias_codes": ",".join(concept.alias_ids.mapped("name")),
            "bc3_category": concept.category,
            "bc3_type": concept.concept_type,
            "bc3_unit_name": concept.unit_name,
            "bc3_price_date_raw": concept.price_date_raw,
            "bc3_text": concept.text,
            "bc3_technical_json": concept.technical_json,
            "bc3_media_refs": "\n".join(concept.media_ref_ids.mapped("filename")),
            "bc3_last_import_date": fields.Datetime.now(),
        }
        if brand and "brand_id" in self.env["product.template"]._fields:
            vals["brand_id"] = brand.id
        if concept.text:
            vals["description_sale"] = concept.text
            if "description_ecommerce" in self.env["product.template"]._fields:
                vals["description_ecommerce"] = "<p>%s</p>" % html.escape(concept.text).replace("\n", "<br/>")
        ProductModel = self.env["product.template"]
        if uom:
            if "uom_id" in ProductModel._fields:
                vals["uom_id"] = uom.id
            if "uom_po_id" in ProductModel._fields:
                vals["uom_po_id"] = uom.id
        product_type = self._map_product_type(concept.concept_type)
        if "type" in ProductModel._fields:
            vals["type"] = product_type
        elif "detailed_type" in ProductModel._fields:
            vals["detailed_type"] = product_type
        if "is_storable" in ProductModel._fields:
            vals["is_storable"] = bool(product_type == "consu" and self.track_inventory)
        if self.publish_on_website and "is_published" in ProductModel._fields:
            vals["is_published"] = True
        if self.create_website_categories and "public_categ_ids" in ProductModel._fields:
            leaf = self._get_or_create_public_category(concept, brand)
            if leaf:
                if self.replace_website_categories:
                    vals["public_categ_ids"] = [(6, 0, [leaf.id])]
                else:
                    vals["public_categ_ids"] = [(4, leaf.id)]
        return vals

    def _map_product_type(self, bc3_type):
        if bc3_type in ("1", "2"):
            return "service"
        return self.default_product_type

    def _map_uom(self, unit_code):
        unit_code = clean(unit_code).lower().replace("²", "2").replace("³", "3")
        xmlid_map = {
            "": "uom.product_uom_unit",
            "u": "uom.product_uom_unit",
            "ud": "uom.product_uom_unit",
            "uds": "uom.product_uom_unit",
            "m": "uom.product_uom_meter",
            "m2": "uom.product_uom_square_meter",
            "m3": "uom.product_uom_cubic_meter",
            "kg": "uom.product_uom_kgm",
            "g": "uom.product_uom_gram",
            "t": "uom.product_uom_ton",
            "h": "uom.product_uom_hour",
            "hr": "uom.product_uom_hour",
            "dia": "uom.product_uom_day",
            "d": "uom.product_uom_day",
            "l": "uom.product_uom_litre",
            "lt": "uom.product_uom_litre",
        }
        xmlid = xmlid_map.get(unit_code)
        if xmlid:
            uom = self.env.ref(xmlid, raise_if_not_found=False)
            if uom:
                return uom
        if unit_code:
            Uom = self.env["uom.uom"].sudo()
            return Uom.search([("name", "=ilike", unit_code)], limit=1) or Uom.search([("name", "ilike", unit_code)], limit=1)
        return self.env.ref("uom.product_uom_unit", raise_if_not_found=False)

    def _get_or_create_public_category(self, concept, brand):
        if not brand:
            return False
        Category = self.env["product.public.category"].sudo()
        current = self._get_or_create_category_node(Category, brand.name, self.website_parent_categ_id)
        path = self._get_bc3_category_path(concept)
        if not path:
            path = [_({"work_unit": "Work Units", "resource": "Resources", "other": "Other"}.get(concept.category, "Products"))]
        for label in path:
            current = self._get_or_create_category_node(Category, label, current)
        return current

    def _get_or_create_category_node(self, Category, name, parent):
        name = clean(name)[:120] or _("Products")
        domain = [("name", "=", name), ("parent_id", "=", parent.id if parent else False)]
        category = Category.search(domain, limit=1)
        if category:
            return category
        return Category.create({"name": name, "parent_id": parent.id if parent else False})

    def _get_bc3_category_path(self, concept):
        seen = set()

        def climb(item):
            if not item or item.id in seen:
                return []
            seen.add(item.id)
            parent_line = self.env["bc3.decomposition.line"].search([
                ("file_id", "=", item.file_id.id),
                ("child_concept_id", "=", item.id),
            ], limit=1, order="sequence,id")
            parent = parent_line.parent_concept_id
            if not parent:
                return []
            label = self._category_label(parent) if parent.category == "chapter" else ""
            return climb(parent) + ([label] if label else [])

        return climb(concept)

    def _category_label(self, concept):
        code = (concept.normalized_code or concept.code or "").strip("#")
        if code:
            return "%s - %s" % (code, concept.name or code)
        return concept.name or concept.code

    def _make_media_reader(self, batch=None):
        return MediaRelatedReader(self, batch=batch)

    def _import_ecommerce_media(self, product, concept, zip_reader):
        # Backward-compatible call used by direct/non-batch imports.
        class ZipOnlyReader:
            def __init__(self, reader):
                self.reader = reader
            def read(self, media):
                return self.reader.read(media.filename)
        return self._import_ecommerce_media_with_reader(product, concept, ZipOnlyReader(zip_reader))

    def _import_ecommerce_media_for_batch(self, product, concept, batch):
        reader = MediaRelatedReader(self, batch=batch)
        return self._import_ecommerce_media_with_reader(product, concept, reader)

    def _import_ecommerce_media_with_reader(self, product, concept, reader):
        if not self.import_images:
            return 0, 0
        count = 0
        warnings = 0
        first_set = False
        existing_names = set(product.product_template_image_ids.mapped("name")) if "product_template_image_ids" in product._fields else set()
        for media in concept.media_ref_ids.filtered("is_image"):
            filename, payload = reader.read(media)
            if filename and payload is None:
                warnings += 1
                continue
            if not payload:
                warnings += 1
                continue
            media_name = "%s - %s" % (concept.code, posixpath.basename(filename or media.filename))
            if self.set_first_image and (self.overwrite_image or not product.image_1920) and not first_set:
                product.write({"image_1920": b64(payload)})
                first_set = True
            if "product_template_image_ids" not in product._fields:
                continue
            if media_name in existing_names:
                continue
            self.env["product.image"].sudo().create({
                "name": media_name,
                "product_tmpl_id": product.id,
                "image_1920": b64(payload),
            })
            existing_names.add(media_name)
            count += 1
        return count, warnings
