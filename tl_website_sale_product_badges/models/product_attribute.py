# Copyright Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import fields, models


class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    tl_is_badge = fields.Boolean(
        "Mostrar como distintivo",
        help="Los valores de este atributo se muestran como icono sobre la "
             "imagen del producto, en la ficha y en el listado de la tienda.",
    )
    tl_badge_sequence = fields.Integer("Orden del distintivo", default=10)


class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    # `image` ya existe en el core (se usa con display_type='image'); aquí se
    # reutiliza como icono del distintivo. Si está vacío se pinta el texto.
    tl_badge_text = fields.Char(
        "Texto del distintivo",
        help="Texto corto a mostrar si el valor no tiene imagen. Vacío = el "
             "nombre del valor.",
    )

    def _tl_badge_label(self):
        self.ensure_one()
        return self.tl_badge_text or self.name
