# -*- coding: utf-8 -*-
{
    'name': "Tecniloop - Barcode Employees",
    'summary': "Informar del empleado que realiza la operacion de Picking.",
    'description': """
        Informar del empleado que realiza la operacion de Picking.
    """,
    'author': "Tecniloop",
    'website': "https://www.tecniloop.es",
    'category': 'Operaciones',
    'version': '19.0.1.0.2',
    
    'depends': ['web','stock_barcode','stock','hr','stock_barcode_mrp','stock', 'web_tour', 'web_mobile','mrp_workorder'],
    'data': [
        'views/hr_employee.xml',
        'views/stock_picking.xml',
        'views/menu_root.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'edyma_barcode_employees/static/src/js/custom_stock_barcode.js',
            'edyma_barcode_employees/static/src/js/barcode_custom_mainmenu.js',
            'edyma_barcode_employees/static/src/js/custom_barcode_model.js',
            'edyma_barcode_employees/static/src/js/custom_barcode_model_mrp.js',
            'edyma_barcode_employees/static/src/xml/main_menu.xml',
            'edyma_barcode_employees/static/src/xml/main_custom.xml',
            ],
    },
}



