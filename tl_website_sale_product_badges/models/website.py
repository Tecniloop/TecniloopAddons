# Copyright Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import fields, models


class Website(models.Model):
    _inherit = "website"

    tl_show_badges_catalog = fields.Boolean(
        "Mostrar distintivos en el catálogo",
        default=False,
        help="En la ficha de producto los distintivos se muestran siempre. "
             "Actívalo para que también aparezcan sobre la imagen en el "
             "listado de la tienda (/shop), la lista de deseos y los "
             "snippets de productos.",
    )
    tl_show_availability_catalog = fields.Boolean(
        "Mostrar disponibilidad en el catálogo",
        default=True,
        help="Punto de color de disponibilidad junto al nombre, en el "
             "listado de la tienda.",
    )
    tl_show_extra_fields_catalog = fields.Boolean(
        "Mostrar campos adicionales en el catálogo",
        default=False,
        help="Los campos configurados en la pestaña nativa «Product Page "
             "Extra Fields» de este sitio web (más abajo en este mismo "
             "formulario) se muestran de serie solo en la ficha de producto. "
             "Actívalo para que también aparezcan, de forma compacta, en el "
             "listado de la tienda.",
    )
