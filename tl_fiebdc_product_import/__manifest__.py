# -*- coding: utf-8 -*-
{
    'name': 'TL FIEBDC BC3 Product Import',
    'summary': 'Import products from a ZIP containing a BC3 file and related images/PDFs',
    'version': '19.0.1.0.10',
    'category': 'Inventory/Inventory',
    'author': 'APEN Solutions / ChatGPT',
    'license': 'LGPL-3',
    'depends': ['base', 'product', 'uom', 'stock', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/fiebdc_import_wizard_views.xml',
        'views/fiebdc_import_batch_views.xml',
        'views/product_template_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
}
