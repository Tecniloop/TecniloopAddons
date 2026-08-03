# Copyright Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import api, fields, models

AVAILABILITY_STYLE = {
    "available": ("tl-dot-available", "Disponible"),
    "limited": ("tl-dot-limited", "Pocas unidades"),
    "preorder": ("tl-dot-preorder", "Reserva"),
    "unavailable": ("tl-dot-unavailable", "No disponible"),
}


class ProductTemplate(models.Model):
    _inherit = "product.template"

    tl_availability = fields.Selection(
        [
            ("available", "Disponible"),
            ("limited", "Pocas unidades"),
            ("preorder", "Reserva / anuncio"),
            ("unavailable", "No disponible"),
        ],
        "Disponibilidad mostrada",
        help="Punto de color en la ficha y en el listado. Vacío = no se "
             "muestra nada.",
    )
    tl_availability_note = fields.Char(
        "Detalle de disponibilidad",
        help="Texto junto al punto, p.ej. 'Envío en 3 días laborables'.",
    )
    tl_badge_value_ids = fields.Many2many(
        "product.attribute.value",
        string="Distintivos",
        compute="_compute_tl_badge_value_ids",
        help="Valores de atributos marcados como distintivo.",
    )

    @api.depends("attribute_line_ids.value_ids",
                 "attribute_line_ids.attribute_id.tl_is_badge")
    def _compute_tl_badge_value_ids(self):
        for template in self:
            lineas = template.attribute_line_ids.filtered(
                lambda l: l.attribute_id.tl_is_badge
            ).sorted(lambda l: l.attribute_id.tl_badge_sequence)
            template.tl_badge_value_ids = lineas.value_ids

    def _tl_availability_class(self):
        self.ensure_one()
        return AVAILABILITY_STYLE.get(self.tl_availability, ("", ""))[0]

    def _tl_availability_label(self):
        self.ensure_one()
        etiqueta = AVAILABILITY_STYLE.get(self.tl_availability, ("", ""))[1]
        return self.tl_availability_note or etiqueta
