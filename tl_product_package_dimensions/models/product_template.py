from odoo import api, fields, models, _
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
        default=lambda self: self.env.ref(
            'uom.product_uom_millimeter', raise_if_not_found=False
        ),
        help='Unidad común para longitud, anchura y altura del embalaje.',
    )
    package_weight = fields.Float(
        string='Peso del embalaje',
        help='Peso bruto del producto con su embalaje.',
    )
    package_weight_uom_id = fields.Many2one(
        'uom.uom',
        string='Unidad de peso del embalaje',
        default=lambda self: self.env.ref(
            'uom.product_uom_kgm', raise_if_not_found=False
        ),
    )
    package_volume_m3 = fields.Float(
        string='Volumen del embalaje (m³)',
        compute='_compute_package_volume_m3',
        store=True,
        digits=(16, 9),
        help='Volumen exterior calculado a partir de las tres dimensiones del embalaje.',
    )

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
            if not uom._has_common_reference(meter):
                product.package_volume_m3 = 0.0
                continue
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
                raise ValidationError(
                    _('Las dimensiones y el peso del embalaje no pueden ser negativos.')
                )

    @api.constrains('package_dimensional_uom_id')
    def _check_package_dimensional_uom(self):
        meter = self.env.ref('uom.product_uom_meter', raise_if_not_found=False)
        if not meter:
            return
        for product in self.filtered('package_dimensional_uom_id'):
            if not product.package_dimensional_uom_id._has_common_reference(meter):
                raise ValidationError(
                    _('La unidad de dimensiones del embalaje debe ser una unidad de longitud.')
                )

    @api.constrains('package_weight_uom_id')
    def _check_package_weight_uom(self):
        kilogram = self.env.ref('uom.product_uom_kgm', raise_if_not_found=False)
        if not kilogram:
            return
        for product in self.filtered('package_weight_uom_id'):
            if not product.package_weight_uom_id._has_common_reference(kilogram):
                raise ValidationError(
                    _('La unidad de peso del embalaje debe ser una unidad de peso.')
                )
