# Copyright Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import _, fields, models
from odoo.exceptions import UserError


class TlPikoImportWizard(models.TransientModel):
    _name = "tl.piko.import.wizard"
    _description = "Importar productos por URL"

    source_id = fields.Many2one("tl.piko.source", required=True)
    urls = fields.Text("URLs (una por línea)", required=True)
    run_now = fields.Boolean(
        "Ejecutar ahora (síncrono)",
        help="Solo para pocas URLs: bloquea la sesión mientras descarga. "
             "Desmarcado, el trabajo se encola y lo hace el cron.",
    )

    def action_run(self):
        self.ensure_one()
        Line = self.env["tl.piko.product"]
        scraper = self.env["tl.piko.scraper"]
        lines = Line.browse()
        for url in [u.strip() for u in self.urls.splitlines() if u.strip()]:
            line = Line.search(
                [("source_id", "=", self.source_id.id), ("url", "=", url)], limit=1
            )
            if not line:
                line = Line.create(
                    {
                        "source_id": self.source_id.id,
                        "url": url,
                        "external_id": scraper._external_id(url),
                    }
                )
            lines |= line
        if not lines:
            raise UserError(_("No se ha indicado ninguna URL válida."))
        if self.run_now:
            lines.action_scrape()
            if self.source_id.auto_import:
                lines.filtered(lambda l: l.state == "parsed").action_import()
        else:
            lines.action_enqueue()
        return {
            "type": "ir.actions.act_window",
            "name": _("Productos rastreados"),
            "res_model": "tl.piko.product",
            "view_mode": "list,form",
            "domain": [("id", "in", lines.ids)],
        }
