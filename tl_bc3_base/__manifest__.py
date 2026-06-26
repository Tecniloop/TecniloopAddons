{
    'name': 'TL BC3 Base',
    'summary': 'Parser BC3/FIEBDC, conceptos, descomposiciones y mediciones',
    'version': '19.0.1.1.6',
    'category': 'Construction/BC3',
    'author': 'Tecniloop',
    'website': 'https://www.tecniloop.com',
    'license': 'AGPL-3',
    'depends': ['base', 'mail', 'uom'],
    'data': ['security/ir.model.access.csv', 'views/bc3_file_views.xml', 'views/bc3_concept_views.xml', 'views/bc3_decomposition_views.xml', 'views/bc3_measurement_views.xml', 'views/bc3_menu_views.xml', 'wizards/bc3_import_wizard_views.xml'],
    'installable': True,
    'application': True,
}
