# -*- coding: utf-8 -*-
# Part of Softhealer Technologies.
{
    "name": "Product Social Media Sharing",
    "author": "Softhealer Technologies",
    "website": "https://www.softhealer.com",
    "support": "support@softhealer.com",
    "category": "Website",
    "license": "OPL-1",
    "summary": """
Product Share On Social Media,
 Social Platform Product Share,
 website Product Share App,
 Shop Product Social Share,
 Product Sharing Odoo,
 Facebook, Twitter,
Linkedin, Whatsapp,
 Email,Reddit,Hacker News,
Digg,TumblrShare Product""",

    "description": """ A social network is a great platform for product advertisement. Currently, in odoo, you have no option to share the product on social media.This module helps you to quickly share the product on social media in a single click.You can share a product from the website shop product page to social media like Facebook, Twitter, LinkedIn, WhatsApp,email, Pinterest, Reddit, Hacker News, Digg, Tumblr.""",

    "version": "19.0.1.0.0",
    "depends": [
        "website_sale"
    ],
    "application": True,
    "data": [
        "views/res_config_settings_views.xml",
        "views/website_views.xml",
        "views/website_sale_templates.xml",
    ],
    'assets': {
        'web.assets_frontend': [
            'sh_product_social_sharing/static/src/js/sh_product_social_sharing.js',
            'sh_product_social_sharing/static/src/js/sh_product_social_sharing_custom.js',
            'sh_product_social_sharing/static/src/scss/sh_product_social_sharing.scss',
        ],
    },
    "images": ["static/description/background.png", ],
    "live_test_url": "https://youtu.be/XV6lixiuTFY",
    "auto_install": False,
    "installable": True,
    "price": 25,
    "currency": "EUR"
}
