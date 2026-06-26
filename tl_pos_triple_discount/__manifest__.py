# -*- coding: utf-8 -*-
{
    "name": "POS Triple Discount",
    "summary": "Triple discount support in POS and POS/Sale order integration",
    "version": "19.0.1.2.0",
    "category": "Sales/Point of Sale",
    "author": "Tecniloop",
    "license": "AGPL-3",
    "depends": [
        "point_of_sale",
        "pos_sale",
    ],
    "data": [],
    "assets": {
        "point_of_sale._assets_pos": [
            "tl_pos_triple_discount/static/src/**/*",
        ],
    },
    "installable": True,
    "application": False,
}
