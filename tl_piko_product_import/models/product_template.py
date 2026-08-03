# Copyright Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import logging

from odoo import fields, models

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

    def _tl_piko_display_properties(self):
        """Propiedades listas para pintar: [{'label':…, 'value':…}, …].

        `product_properties` no tiene un formato único: según cómo se acceda
        devuelve un dict {clave: valor} o una lista de dicts con 'name',
        'string' y 'value'. Normalizarlo aquí evita tener que adivinarlo en
        QWeb, donde un fallo tumba el renderizado de la página entera.
        """
        self.ensure_one()
        if "product_properties" not in self._fields:
            return []
        bruto = self.product_properties or []
        rotulos = {
            definicion.get("name"): definicion.get("string")
            for definicion in (self.categ_id.product_properties_definition or [])
        }
        if isinstance(bruto, dict):
            pares = list(bruto.items())
        else:
            pares = []
            for propiedad in bruto:
                if isinstance(propiedad, dict):
                    pares.append((propiedad.get("name"), propiedad.get("value")))
                    rotulos.setdefault(propiedad.get("name"),
                                       propiedad.get("string"))
        salida = []
        for clave, valor in pares:
            if valor in (False, None, ""):
                continue
            salida.append({
                "label": rotulos.get(clave) or clave,
                "value": valor,
            })
        return salida

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
