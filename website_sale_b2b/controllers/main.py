# -*- coding: utf-8 -*-
# Part of SoftMuch. See LICENSE file for full copyright and licensing details.

from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSale(WebsiteSale):
    @http.route()
    def product(self, product, category='', search='', **kwargs):
        res = super(WebsiteSale, self).product(product, category, search, **kwargs)
        # Set the order in the product view
        res.qcontext['order'] = request.website.sale_get_order(force_create=False)
        res.qcontext['partner'] = request.env.user.partner_id
        return res

    @http.route()
    def shop(self, page=0, category=None, search='', min_price=0.0, max_price=0.0, ppg=False, **post):
        res = super(WebsiteSale, self).shop(page, category, search, ppg, **post)

        order = request.website.sale_get_order(force_create=False)
        res.qcontext['sale_order'] = order
        res.qcontext['partner'] = request.env.user.partner_id

        # if order.pricelist_id.web_display_mode == 'wholesale':
        #     res.qcontext['layout_mode'] = 'list'

        return res

    @http.route()
    def cart_update_json(
        self, product_id, line_id=None, add_qty=None, set_qty=None, display=True,
        product_custom_attribute_values=None, no_variant_attribute_values=None, **kw
    ):
        # Search for the line_id if it exists
        order = request.website.sale_get_order(force_create=False)
        lines = order.order_line.filtered(lambda line: line.product_id.id == product_id)
        if lines:
            line_id = lines[0].id

        return super(WebsiteSale, self).cart_update_json(
            product_id, line_id, add_qty, set_qty, display, product_custom_attribute_values,
        )

    @http.route(['/website_sale_b2b/show_product_matrix_website'], type='json', auth="public", website=True, sitemap=True)
    def show_product_matrix_website(self, product_id):
        product = request.env['product.template'].sudo().browse(product_id)

        values = self._prepare_product_values(product, '', '')
        values['order'] = request.website.sale_get_order(force_create=False)
        values['partner'] = request.env.user.partner_id

        return request.env['ir.ui.view']._render_template("website_sale_b2b.matrix_modal", values)

    @http.route(['/website_sale_b2b/get_product_quantities'], type='json', auth="public", website=True, sitemap=True)
    def get_product_quantities(self, product_ids):
        if request.website.pricelist_id.web_display_mode == 'wholesale':
            order = request.website.sale_get_order(force_create=False)
            response = []
            for product_id in product_ids:
                lines = order.order_line.filtered(lambda line: line.product_id.id == product_id)
                if lines:
                    line = lines[0]
                    response.append({'product_id': product_id, 'qty': line.product_uom_qty})
                else:
                    response.append({'product_id': product_id, 'qty': 0})

            return response
        return False

    @http.route(['/website_sale_b2b/add_description'], type='json', auth="public", website=True, sitemap=True)
    def add_description(self, product_id, value):
        order = request.website.sale_get_order(force_create=False)
        lines = order.order_line.filtered(lambda line: line.product_id.id == product_id)

        if not lines:
            res = "You have to add some products in order to add a description."
        elif not value:
            res = "No description added, please add one."
        else:
            res = "Description '" + value + "' was added to the order line."

        for line in lines:
            line.name += '\n\n Customization: ' + value

        return res