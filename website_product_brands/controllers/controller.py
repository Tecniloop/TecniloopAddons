# -*- coding: utf-8 -*-
#################################################################################
#
# Copyright (c) 2017-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#   See LICENSE URL <https://store.webkul.com/license.html/> for full copyright and licensing details.
#################################################################################

import logging

from werkzeug.exceptions import NotFound
from odoo import http
from odoo.http import request, route
from odoo.tools import lazy, groupby
from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.addons.website_sale.controllers.main import TableCompute, QueryURL

_logger = logging.getLogger(__name__)


class WebsiteSale(WebsiteSale):

    @route(
        ['''/shop''',
         '''/shop/page/<int:page>''',
         '''/shop/category/<model("product.public.category"):category>''',
         '''/shop/category/<model("product.public.category"):category>/page/<int:page>''',
         '''/shop/brand/<model("wk.product.brand"):wk_brand>''',
         '''/shop/brand/<model("wk.product.brand"):wk_brand>/page/<int:page>'''],
        type='http', auth="public", website=True)
    def shop(self, wk_brand=None, page=0, category=None, search='', ppg=False, **post):
        brand_set=[]

        if wk_brand and wk_brand.exists():
            brand_set.append(wk_brand.id)
            request.session['wk_brand'] = wk_brand.id
        else:
            request.session['wk_brand'] = False

        response= super(WebsiteSale, self).shop(page=page, category=category,
            search=search, ppg=ppg, **post)

        attrib_brands = request.httprequest.args.getlist('attrib_brand')
        parsed_ids = set()
        for v in attrib_brands:
            s = (str(v).strip()) if v is not None else ""
            if not s:
                continue
            # Formato select simple: "42"
            try:
                parsed_ids.add(int(s))
                continue
            except ValueError:
                pass
            # Formato antiguo tipo "12-42": tomamos la segunda parte
            if "-" in s:
                try:
                    second = s.split("-", 1)[1].strip()
                    if second:
                        parsed_ids.add(int(second))
                except (IndexError, ValueError):
                    pass

        # Mantener preselección de /shop/brand/<wk_brand> y añadir lo parseado
        brand_set = set(brand_set) | parsed_ids

        response.qcontext['brand_set'] = list(brand_set)
        response.qcontext['brand_rec'] = request.env['wk.product.brand'].search([
            ('website_published', '=', True),
            ('website_id', 'in', [request.website.id, False]),
        ])
        response.qcontext['wk_brands'] = request.env['wk.product.brand'].browse(list(brand_set))
        # --- FIN PARSEO ROBUSTO ---

        if ppg:
            try:
                ppg = int(ppg)
                post['ppg'] = ppg
            except ValueError:
                ppg = False
        if not ppg:
            ppg = request.env['website'].get_current_website().shop_ppg or 20

        ppr = request.env['website'].get_current_website().shop_ppr or 4

        qcontext = dict(response.qcontext)
        attrib_list = request.httprequest.args.getlist('attrib')

        if category:
            if isinstance(category, (str, int)):
                try:
                    category = request.env['product.public.category'].browse(int(category))
                except (ValueError, TypeError):
                    pass
            try:
                url = "/shop/category/%s" % request.env['ir.http']._slug(category)
            except Exception:
                url = "/shop/category/%s" % category
        elif wk_brand:
            if isinstance(wk_brand, (str, int)):
                try:
                    wk_brand = request.env['wk.product.brand'].browse(int(wk_brand))
                except (ValueError, TypeError):
                    pass
            try:
                url = "/shop/brand/%s" % request.env['ir.http']._slug(wk_brand)
            except Exception:
                url = "/shop/brand/%s" % wk_brand
        else:
            url = "/shop"

        if search:
            post["search"] = search

        if attrib_list:
            post['attrib'] = attrib_list

        pager = request.website.pager(url=url, total=qcontext.get('search_count'),
                                    page=page, step=ppg, scope=7, url_args=post)
        response.qcontext['pager'] = pager

        keep = QueryURL(
            '/shop',
            category=category.id if hasattr(category, 'id') else category,
            wk_brand=wk_brand.id if hasattr(wk_brand, 'id') else wk_brand,
            search=search,
            attrib=attrib_list,
            order=post.get('order'),
            attrib_brand=attrib_brands
        )

        response.qcontext['keep'] = keep
        return response

    def _get_brand_search_domain(self, search):
        domain = [
            ("website_published", "=", True),
            ('website_id', 'in', [request.website.id, False])
        ]
        if search:
            for srch in search.split(" "):
                domain += [('name', 'ilike', srch)]
        return domain

    @http.route(['/shop/brands', '/shop/brands/page/<int:page>'], type='http', auth="public", website=True)
    def wk_brands_page(self, brand=False, page=0, search='', ppg=False, **post):
        website = request.env['website'].get_current_website()
        if ppg:
            try:
                ppg = int(ppg)
                post["ppg"] = ppg
            except ValueError:
                ppg = False

        if not ppg:
            ppg = website.shop_ppg or 20

        PPR = website.shop_ppr or 4

        keep = QueryURL('/shop/brands', search=search)

        url = "/shop/brands"
        if search:
            post["search"] = search

        layout_mode = request.session.get('website_sale_shop_layout_mode')
        if not layout_mode:
            if request.website.viewref('website_sale.products_list_view').active:
                layout_mode = 'list'
            else:
                layout_mode = 'grid'

        wk_product_brand_obj = request.env['wk.product.brand'].search(
            self._get_brand_search_domain(search))
        wk_brands_count = len(wk_product_brand_obj)
        pager = request.website.pager(
            url=url, total=wk_brands_count, page=page, step=ppg, scope=7, url_args=post)
        offset = pager['offset']
        wk_product_brand_obj = wk_product_brand_obj[offset:offset+ppg]

        values = {
            'search': search,
            'pager': pager,
            'wk_brands_list': wk_product_brand_obj,
            'search_count': wk_brands_count,  # common for all searchbox
            'bins': TableCompute().process(wk_product_brand_obj, ppg, PPR),
            'ppg': ppg,
            'ppr': PPR,
            'rows': 4,
            'keep': keep,
            'layout_mode': layout_mode,
        }
        return request.render("website_product_brands.wk_brands_page", values)

    def brand_category_domain(self, brand_id):
        category_ids = []
        for product in brand_id.products:
            category_ids.extend(product.public_categ_ids.ids)
        unique_category_ids = list(set(category_ids))
        if not unique_category_ids:
            return []
        return [('id', 'in', unique_category_ids)]

    @http.route(['/product/brand/<int:brand>',
                '''/product/brand/<int:brand>/page/<int:page>''',
                 '''/product/brand/<int:brand>/category/<model("product.public.category"):category>''',
                 '''/product/brand/<int:brand>/category/<model("product.public.category"):category>/page/<int:page>'''
                 ], type='http', auth="public", website=True)
    def wk_product_brand(self, brand=False, category=None, page=0, search='', ppg=False, **post):
        Category = request.env['product.public.category']
        if category:
            category = Category.search([('id', '=', int(category))], limit=1)
            if not category or not category.can_access_from_current_website():
                raise NotFound()
        else:
            category = Category

        website = request.env['website'].get_current_website()

        if ppg:
            try:
                ppg = int(ppg)
                post["ppg"] = ppg
            except ValueError:
                ppg = False

        if not ppg:
            ppg = website.shop_ppg or 20

        PPR = website.shop_ppr or 4

        request_args = request.httprequest.args
        attrib_list = request_args.getlist('attrib')
        attrib_values = [
            [int(x) for x in v.split("-")]
            for v in attrib_list if v
        ]
        attributes_ids = {v[0] for v in attrib_values}
        attrib_set = {v[1] for v in attrib_values}

        url = "/product/brand/" + str(brand)

        keep = QueryURL(url, category=category and int(
            category), search=search, attrib=attrib_list, order=post.get('order'))

        if search:
            post["search"] = search

        if category:
            url = "/shop/category/%s" % request.env['ir.http']._slug(category)
        wk_brand_product = request.env["wk.product.brand"]
        if brand:
            wk_brand = request.env["wk.product.brand"].search(
                [('id', '=', brand), ('website_published', '=', True)])
        if wk_brand:
            wk_brand_product = wk_brand.products.search(self._get_shop_domain(
                search, category, attrib_values)+[('product_brand_id.id', '=', brand)], order=self._get_search_order(post))
        product_count = len(wk_brand_product)

        categs_domain = [('parent_id', '=', False)] + \
            self.brand_category_domain(wk_brand)
        if search:
            search_categories = Category.search(
                [('product_tmpl_ids', 'in', wk_brand_product.ids)]).parents_and_self
            categs_domain.append(('id', 'in', search_categories.ids))
        else:
            search_categories = Category

        search_id = request.env["wk.product.brand"].search(
            [('id', '=', brand)]
        )
        country_origin = search_id.country_of_origin

        categs = lazy(lambda: Category.search(categs_domain))

        pager = request.website.pager(
            url=url, total=product_count, page=page, step=ppg, scope=7, url_args=post)
        offset = pager['offset']
        wk_brand_product = wk_brand_product[offset:offset+ppg]

        layout_mode = request.session.get('website_sale_shop_layout_mode')
        if not layout_mode:
            if request.website.viewref('website_sale.products_list_view').active:
                layout_mode = 'list'
            else:
                layout_mode = 'grid'
            request.session['website_sale_shop_layout_mode'] = layout_mode

        ProductAttribute = request.env['product.attribute']
        if wk_brand_product:
            # get all products without limit
            attributes = ProductAttribute.search([
                ('product_tmpl_ids', 'in', wk_brand_product.ids)
            ])
        else:
            attributes = ProductAttribute.browse(attributes_ids)

        products_prices = lazy(
            lambda: wk_brand.products._get_sales_prices(website))
        attributes_values = request.env['product.attribute.value'].browse(
            attrib_set)
        sorted_attributes_values = attributes_values.sorted('sequence')
        multi_attributes_values = sorted_attributes_values.filtered(
            lambda av: av.display_type == 'multi')
        single_attributes_values = sorted_attributes_values - multi_attributes_values
        grouped_attributes_values = list(
            groupby(single_attributes_values, lambda av: av.attribute_id.id)
        )
        grouped_attributes_values.extend(
            [(av.attribute_id.id, [av]) for av in multi_attributes_values]
        )

        selected_attributes_hash = grouped_attributes_values and "#attribute_values=%s" % (
            ','.join(str(v[0].id) for k, v in grouped_attributes_values)
        ) or ''

        values = {
            'search': search,
            'category': category,
            'pager': pager,
            'wk_brand': wk_brand,
            'brand_product': wk_brand_product,
            'search_count': wk_brand.total_products,  # common for all searchbox
            'bins': TableCompute().process(wk_brand_product, ppg, PPR),
            'ppg': ppg,
            'ppr': PPR,
            'rows': 4,
            'categories': categs,
            'keep': keep,
            'layout_mode': layout_mode,
            'attrib_values': attrib_values,
            'attrib_set': attrib_set,
            'attributes': attributes,
            'country_origin': country_origin,
            'products_prices': products_prices,
            'get_product_prices': lambda product: lazy(lambda: products_prices[product.id]),
            'selected_attributes_hash': selected_attributes_hash
        }
        values.update(self._get_additional_shop_values(values))

        return request.render("website_product_brands.wk_product_brand_page", values)

    @http.route(['/get/product/brands'], type='json', auth="public", website=True)
    def get_product_brand(self, **post):
        value = {
            'brands': request.env['wk.product.brand'].search([('website_published', '=', True)], limit=9),
        }
        response = request.env['ir.ui.view'].sudo()._render_template(
            'website_product_brands.website_product_brands_carousal', value
        )
        return response
