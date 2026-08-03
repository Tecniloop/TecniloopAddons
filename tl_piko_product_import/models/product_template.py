# Copyright Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.queue_job.job import identity_exact

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    piko_source_id = fields.Many2one("tl.piko.source", "Fuente de scraping", copy=False)
    piko_external_id = fields.Char("ID externo", copy=False, index=True)
    piko_url = fields.Char("URL de origen", copy=False)
    piko_last_sync = fields.Datetime("Última sincronización", copy=False, readonly=True)
    piko_price_locked = fields.Boolean(
        "Precio fijado manualmente",
        help="Si está marcado, el importador nunca sobrescribe el precio de venta.",
    )
    piko_no_overwrite = fields.Boolean(
        "No sobrescribir",
        help="Excluye este producto de cualquier actualización automática.",
    )

    def action_tl_piko_refresh_description(self):
        """Rectifica la descripción de eCommerce de los productos elegidos.

        Si la línea de staging ya tiene la descripción rastreada, se aplica al
        momento. Si no la tiene (productos importados antes de que el módulo
        extrajera el HTML), se encola un job que vuelve a leer la ficha.
        """
        Line = self.env["tl.piko.product"]
        candidatos = self.filtered(lambda p: p.piko_url or p.piko_external_id)
        if not candidatos:
            raise UserError(
                _("Ninguno de los productos seleccionados procede de una "
                  "importación por scraping.")
            )
        directos = Line.browse()
        encolados = 0
        for product in candidatos:
            line = Line.search(
                [("product_tmpl_id", "=", product.id)], limit=1
            ) or Line.search([("url", "=", product.piko_url)], limit=1)
            if not line:
                continue
            if line.description_html or line.description:
                directos |= line
            else:
                line.with_delay(
                    description=_("Releer descripción de %s") % product.display_name,
                    identity_key=identity_exact,
                    priority=5,
                )._job_refresh_description()
                encolados += 1
        directos.action_push_description()
        mensaje = _("%(directos)s descripciones actualizadas, "
                    "%(encolados)s fichas encoladas para releer.",
                    directos=len(directos), encolados=encolados)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("PIKO Import"), "message": mensaje,
                       "type": "success", "sticky": True},
        }

    def action_open_piko_url(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": self.piko_url, "target": "new"}


class ProductCategory(models.Model):
    _inherit = "product.category"

    piko_external_id = fields.Char(
        "Id de categoría de origen", copy=False, index=True,
        help="Id de la categoría en la tienda rastreada; evita duplicar el "
             "árbol si allí renombran una categoría.",
    )


class ProductPublicCategory(models.Model):
    # Solo se registra si website_sale está instalado.
    _inherit = "product.public.category"

    piko_external_id = fields.Char(
        "Id de categoría de origen", copy=False, index=True
    )
