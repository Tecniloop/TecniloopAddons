# -*- coding: utf-8 -*-
#################################################################################
# Author      : Webkul Software Pvt. Ltd. (<https://webkul.com/>)
# Copyright(c): 2015-Present Webkul Software Pvt. Ltd.
# All Rights Reserved.
#
#
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#
# You should have received a copy of the License along with this program.
# If not, see <https://store.webkul.com/license.html/>
#################################################################################
{
    "name":  "Website Product Brand",
    "summary":  """The module allows users to filter products by brand on the Odoo website. Users can create brand records
                    and assign products to them.""",
    "category":  "Website",
    "version":  "1.0.4",
    "sequence":  1,
    "author":  "Webkul Software Pvt. Ltd.",
    "license":  "Other proprietary",
    "website":  "https://store.webkul.com/Odoo-Website-Product-Brand.html",
    "description":  """This module enables product filtering by brand on your Odoo website, making it easier for customers
                    to find what they're looking for. Users can easily create brand records and assign relevant products to
                    each brand, providing a more organized and efficient shopping experience. This feature enhances website
                    navigation and improves customer satisfaction by offering streamlined brand-specific browsing.
                    Odoo brand filter | Filter products by brand | Odoo product filtering | Brand records in Odoo | Product
                    brand assignment | Odoo website filter | Brand-based product filter | Odoo brand management | Create 
                    brand records | Product filter module | Odoo website brands | Brand filter feature""",
    "live_test_url":  "http://odoodemo.webkul.com/?module=website_product_brands",
    "depends":  ['website_sale'],
    "data":  [
        'security/ir.model.access.csv',
        'data/data.xml',
        'data/menu.xml',
        'views/website_product_brands.xml',
        'views/template.xml',
        'views/snippet_template.xml',
    ],
    "images":  ['static/description/Banner.png'],
    "application":  True,
    "installable":  True,
    'assets': {
        'web.assets_frontend': [
            'website_product_brands/static/src/**/*',
        ],
    },
    "price":  49,
    "currency":  "USD",
    "pre_init_hook":  "pre_init_check",
}
