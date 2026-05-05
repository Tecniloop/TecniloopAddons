# -*- coding: utf-8 -*-
# Part of SoftMuch. See LICENSE file for full copyright and licensing details.

from odoo import models
from datetime import datetime
from odoo.http import request


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def get_web_matrix(self, product_template):
        matrix = super(SaleOrder, self)._get_matrix(product_template)
        pricelist = request.website.pricelist_id
        matrix['header'][0] = {'name': ''}

        # Add max stock and variant_id
        for row in matrix['matrix']:
            # Don't show when there is more than an attribute
            # row[0]['name'] = row[0]['name'].split('•')[0]
            for col in row[1:]:
                combination = self.env['product.template.attribute.value'].sudo().search([('id', 'in', col['ptav_ids'])])
                product = self.env['product.template'].sudo().browse(product_template.id)._get_variant_for_combination(combination)

                # Variant with custom value (is_custom)
                col['is_custom'] = False
                col['value_id'] = False
                col['value_name'] = False
                for comb in combination:
                    if comb.is_custom:
                        col['is_custom'] = True
                        col['value_id'] = comb.id
                        col['value_name'] = comb.name

                # Control if the quantity should be finite or infinite
                is_finite_qty = ('free_qty' in product and
                                 'inventory_availability' in product and
                                 product.inventory_availability != 'never')

                col['free_qty'] = product.sudo().free_qty if is_finite_qty else False
                col['variant_id'] = product.id

                # The product was already created
                if product:
                    col['free_qty'] = product.sudo().free_qty if is_finite_qty else False
                    col['product_id'] = product.product_tmpl_id.id
                    col['variant_id'] = product.id
                    price = pricelist._get_product_price(product, 1, date=datetime.now())
                    col['price'] = price
                # The product doesn't exist, it's going to be created dynamically
                else:
                    is_dynamic = len(combination.attribute_id.filtered(lambda attribute: attribute.create_variant == 'dynamic')) > 0
                    if is_dynamic:
                        col['free_qty'] = False
                        col['product_id'] = product_template.id
                        col['variant_id'] = False
                        combination_info = product_template._get_combination_info(combination=combination, product_id=product_template.product_variant_id.id, add_qty=1.0)
                        col['price'] = combination_info['price']
        return matrix