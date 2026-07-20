from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    package_length = fields.Float(
        string='Longitud del embalaje',
        help='Longitud exterior del embalaje físico del producto.',
    )
    package_width = fields.Float(
        string='Anchura del embalaje',
        help='Anchura exterior del embalaje físico del producto.',
    )
    package_height = fields.Float(
        string='Altura del embalaje',
        help='Altura exterior del embalaje físico del producto.',
    )
    package_dimensional_uom_id = fields.Many2one(
        'uom.uom',
        string='Unidad de dimensiones del embalaje',
        domain="[('category_id', '=', package_dimensional_uom_category_id)]",
        default=lambda self: self.env.ref('uom.product_uom_millimeter', raise_if_not_found=False),
        help='Unidad común para longitud, anchura y altura del embalaje.',
    )
    package_dimensional_uom_category_id = fields.Many2one(
        'uom.category',
        compute='_compute_package_uom_categories',
    )
    package_weight = fields.Float(
        string='Peso del embalaje',
        help='Peso bruto del producto con su embalaje.',
    )
    package_weight_uom_id = fields.Many2one(
        'uom.uom',
        string='Unidad de peso del embalaje',
        domain="[('category_id', '=', package_weight_uom_category_id)]",
        default=lambda self: self.env.ref('uom.product_uom_kgm', raise_if_not_found=False),
    )
    package_weight_uom_category_id = fields.Many2one(
        'uom.category',
        compute='_compute_package_uom_categories',
    )
    package_volume_m3 = fields.Float(
        string='Volumen del embalaje (m³)',
        compute='_compute_package_volume_m3',
        store=True,
        digits=(16, 9),
        help='Volumen exterior calculado a partir de las tres dimensiones del embalaje.',
    )

    @api.depends_context('lang')
    def _compute_package_uom_categories(self):
        length_uom = self.env.ref('uom.product_uom_meter', raise_if_not_found=False)
        weight_uom = self.env.ref('uom.product_uom_kgm', raise_if_not_found=False)
        for product in self:
            product.package_dimensional_uom_category_id = length_uom.category_id if length_uom else False
            product.package_weight_uom_category_id = weight_uom.category_id if weight_uom else False

    @api.depends(
        'package_length',
        'package_width',
        'package_height',
        'package_dimensional_uom_id',
    )
    def _compute_package_volume_m3(self):
        meter = self.env.ref('uom.product_uom_meter', raise_if_not_found=False)
        for product in self:
            if not meter or not product.package_dimensional_uom_id or not all((
                product.package_length,
                product.package_width,
                product.package_height,
            )):
                product.package_volume_m3 = 0.0
                continue
            uom = product.package_dimensional_uom_id
            length_m = uom._compute_quantity(product.package_length, meter, round=False)
            width_m = uom._compute_quantity(product.package_width, meter, round=False)
            height_m = uom._compute_quantity(product.package_height, meter, round=False)
            product.package_volume_m3 = length_m * width_m * height_m

    @api.constrains(
        'package_length',
        'package_width',
        'package_height',
        'package_weight',
    )
    def _check_package_measurements(self):
        for product in self:
            values = (
                product.package_length,
                product.package_width,
                product.package_height,
                product.package_weight,
            )
            if any(value < 0 for value in values):
                raise ValidationError('Las dimensiones y el peso del embalaje no pueden ser negativos.')
