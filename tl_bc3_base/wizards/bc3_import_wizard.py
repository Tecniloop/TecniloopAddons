import os
import posixpath
import urllib.parse

from odoo import _, fields, models
from odoo.exceptions import UserError


class Bc3ImportWizard(models.TransientModel):
    _name = "bc3.import.wizard"
    _description = "BC3 Import Wizard"

    name = fields.Char(default=lambda self: _("BC3 import"), required=True)
    source_type = fields.Selection(
        [("upload", "Uploaded File"), ("url", "URL"), ("server_path", "Server Path")],
        default="upload",
        required=True,
    )
    data_file = fields.Binary(string="BC3 File", attachment=True)
    filename = fields.Char()
    source_url = fields.Char(string="Source URL")
    server_path = fields.Char(string="Server File Path")
    allow_insecure_ssl = fields.Boolean(string="Allow Insecure SSL")
    max_download_size_mb = fields.Integer(string="Max URL Download Size (MB)", default=0)
    parse_now = fields.Boolean(default=True)

    def action_import(self):
        self.ensure_one()
        vals = {
            "name": self._get_default_name(),
            "source_type": self.source_type,
            "filename": self.filename,
            "data_file": self.data_file,
            "source_url": self.source_url,
            "server_path": self.server_path,
            "allow_insecure_ssl": self.allow_insecure_ssl,
            "max_download_size_mb": self.max_download_size_mb,
        }
        if self.source_type == "upload" and not self.data_file:
            raise UserError(_("Please upload a BC3 file."))
        if self.source_type == "url" and not self.source_url:
            raise UserError(_("Please set a URL."))
        if self.source_type == "server_path" and not self.server_path:
            raise UserError(_("Please set a server file path."))
        bc3_file = self.env["bc3.file"].create(vals)
        if self.parse_now:
            bc3_file.action_parse()
        return {
            "type": "ir.actions.act_window",
            "name": _("BC3 File"),
            "res_model": "bc3.file",
            "view_mode": "form",
            "res_id": bc3_file.id,
        }

    def _get_default_name(self):
        self.ensure_one()
        if self.name and self.name != _("BC3 import"):
            return self.name
        if self.filename:
            return self.filename
        if self.source_type == "url" and self.source_url:
            parsed = urllib.parse.urlparse(self.source_url)
            return posixpath.basename(urllib.parse.unquote(parsed.path)) or self.source_url
        if self.source_type == "server_path" and self.server_path:
            return os.path.basename(self.server_path)
        return self.name or _("BC3 import")
