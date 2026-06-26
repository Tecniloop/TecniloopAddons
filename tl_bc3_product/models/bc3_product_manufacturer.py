import html
import posixpath
import urllib.parse

from odoo import _, fields, models
from odoo.exceptions import UserError


def clean(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return "".join(ch for ch in value if ch in ("\t", "\n", "\r") or ord(ch) >= 32).strip()


class Bc3ProductManufacturer(models.Model):
    _name = "bc3.product.manufacturer"
    _description = "BC3 Product Manufacturer URL"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char(string="Manufacturer", required=True, tracking=True)
    active = fields.Boolean(default=True)
    brand_id = fields.Many2one("res.brand", string="Brand")
    bc3_url = fields.Char(string="BC3/ZIP URL", required=True, tracking=True)
    bc3_filename = fields.Char(string="BC3 Filename", help="Optional when the URL points to a ZIP/RAR with more than one BC3.")
    allow_insecure_ssl = fields.Boolean(string="Allow Insecure SSL")
    max_bc3_download_size_mb = fields.Integer(
        string="Max BC3 Download Size (MB)",
        default=0,
        help="0 means no explicit module limit. Server memory and timeout limits still apply.",
    )
    max_related_file_size_mb = fields.Integer(string="Max Related File Size (MB)", default=75)

    update_existing = fields.Boolean(default=True)
    default_product_type = fields.Selection([("consu", "Goods"), ("service", "Service")], default="consu", required=True)
    track_inventory = fields.Boolean(default=True)
    import_work_units = fields.Boolean(default=True)
    import_resources = fields.Boolean(default=True)
    import_other = fields.Boolean(default=True)
    include_zero_price = fields.Boolean(default=True)
    create_website_categories = fields.Boolean(default=True)
    website_parent_categ_id = fields.Many2one("product.public.category", string="Parent Website Category")
    replace_website_categories = fields.Boolean()
    publish_on_website = fields.Boolean()
    import_images = fields.Boolean(default=True)
    set_first_image = fields.Boolean(default=True)
    overwrite_image = fields.Boolean()
    media_server_path = fields.Char(string="Media Server Path")
    import_batch_size = fields.Integer(default=200, required=True)
    process_first_chunk = fields.Boolean(default=True)
    preview_html = fields.Html(readonly=True)
    file_id = fields.Many2one("bc3.file", readonly=True, copy=False)
    last_import_batch_id = fields.Many2one("bc3.product.import.batch", readonly=True, copy=False)
    last_import_date = fields.Datetime(readonly=True, copy=False)

    def action_preview(self):
        self.ensure_one()
        bc3_file = self._get_or_create_bc3_file(parse=True)
        wizard = self._make_wizard(bc3_file)
        concepts = wizard._get_importable_concepts()
        rows = []
        for concept in concepts[:80]:
            rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                html.escape(concept.code or ""),
                html.escape(concept.category or ""),
                html.escape(concept.unit_name or ""),
                html.escape(concept.name or ""),
            ))
        self.preview_html = """
            <p><b>Manufacturer:</b> %s<br/><b>URL:</b> %s<br/><b>BC3 file:</b> %s<br/><b>Importable products:</b> %s</p>
            <table class="table table-sm table-hover"><thead><tr><th>Code</th><th>Category</th><th>UoM</th><th>Name</th></tr></thead><tbody>%s</tbody></table>
        """ % (html.escape(self.name), html.escape(self.bc3_url), html.escape(bc3_file.display_name), len(concepts), "".join(rows))
        return self._open_self()

    def action_import(self):
        self.ensure_one()
        bc3_file = self._get_or_create_bc3_file(parse=True)
        wizard = self._make_wizard(bc3_file)
        batch = wizard._create_import_batch(process_first_chunk=self.process_first_chunk, manufacturer=self)
        self.write({"file_id": bc3_file.id, "last_import_batch_id": batch.id, "last_import_date": fields.Datetime.now()})
        return {
            "type": "ir.actions.act_window",
            "name": _("BC3 Product Import"),
            "res_model": "bc3.product.import.batch",
            "view_mode": "form",
            "res_id": batch.id,
        }

    def action_open_last_import_batch(self):
        self.ensure_one()
        if not self.last_import_batch_id:
            raise UserError(_("This manufacturer has no imports yet."))
        return {
            "type": "ir.actions.act_window",
            "name": _("BC3 Product Import"),
            "res_model": "bc3.product.import.batch",
            "view_mode": "form",
            "res_id": self.last_import_batch_id.id,
        }

    def _get_or_create_bc3_file(self, parse=True):
        self.ensure_one()
        bc3_file = self.file_id
        if bc3_file and bc3_file.source_url == self.bc3_url:
            if parse and bc3_file.state != "parsed":
                bc3_file.action_parse()
            return bc3_file
        name = self.bc3_filename or self._filename_from_url() or self.name
        bc3_file = self.env["bc3.file"].sudo().create({
            "name": "%s - %s" % (self.name, name),
            "source_type": "url",
            "source_url": self.bc3_url,
            "filename": self.bc3_filename or name,
            "allow_insecure_ssl": self.allow_insecure_ssl,
            "max_download_size_mb": self.max_bc3_download_size_mb,
        })
        if parse:
            bc3_file.action_parse()
        self.write({"file_id": bc3_file.id})
        return bc3_file

    def _filename_from_url(self):
        parsed = urllib.parse.urlparse(self.bc3_url or "")
        return clean(posixpath.basename(urllib.parse.unquote(parsed.path)))

    def _get_or_create_brand(self):
        self.ensure_one()
        if self.brand_id:
            return self.brand_id
        Brand = self.env["res.brand"].sudo()
        brand = Brand.search([("name", "=", self.name)], limit=1)
        if brand:
            self.brand_id = brand.id
            return brand
        partner = self.env["res.partner"].sudo().create({"name": self.name, "company_type": "company"})
        brand = Brand.create({"partner_id": partner.id})
        self.brand_id = brand.id
        return brand

    def _make_wizard(self, bc3_file):
        brand = self._get_or_create_brand()
        return self.env["bc3.product.import.wizard"].sudo().create({
            "file_id": bc3_file.id,
            "brand_id": brand.id if brand else False,
            "brand_name": self.name,
            "create_brand": True,
            "import_work_units": self.import_work_units,
            "import_resources": self.import_resources,
            "import_other": self.import_other,
            "include_zero_price": self.include_zero_price,
            "update_existing": self.update_existing,
            "publish_on_website": self.publish_on_website,
            "default_product_type": self.default_product_type,
            "track_inventory": self.track_inventory,
            "create_website_categories": self.create_website_categories,
            "website_parent_categ_id": self.website_parent_categ_id.id if self.website_parent_categ_id else False,
            "replace_website_categories": self.replace_website_categories,
            "import_images": self.import_images,
            "set_first_image": self.set_first_image,
            "overwrite_image": self.overwrite_image,
            "media_server_path": self.media_server_path,
            "max_related_file_size_mb": self.max_related_file_size_mb,
            "batch_size": self.import_batch_size,
        })

    def _open_self(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("BC3 Manufacturer"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
        }
