# -*- coding: utf-8 -*-
{
    'name': "Asistencias Personalizadas",

    'summary': "Este modulo extiende de Asistencias para añadir nuevas funcionalidades al fichaje.",
    'description': """
        Este modulo extiende de Asistencias para añadir nuevas funcionalidades. Añade nuevos botones en el fichaje para poder controlar las entradas de teletrabajo y horas extra.
        Esto se queda grabado en la misma asistencia, y luego se puede filtrar en la vista. Asi podemos tener control de las horas extra acomuladas, las horas extra obligadas acomuladas que van a una bolsa de horas
        y las horas que tienen que ser pagadas en nómina.
    """,

    'author': "Tecniloop",
    'website': "https://www.tecniloop.com",

    'category': 'Asistencias',
    'version': '18.0.1.0.3',

    'depends': ['hr_attendance', 'hr_holidays', 'hr_recruitment'],

    'data': [
        "security/ir.model.access.csv",
        "views/hr_attendance_view.xml",
        "views/hr_employee_views.xml",
        "views/res_config_settings_view.xml",
        "wizard/extra_hours_assign_wizard_views.xml",
        "wizard/undo_allocation_wizard_views.xml",
        "views/hr_leave_calendar_inherit.xml",
    ],
    
    "assets": {
        "web.assets_backend": [
            "tl_attendance_extra/static/src/components/attendance_menu/attendance_menu_inherit.xml",
            "tl_attendance_extra/static/src/js/attendance_menu.js",
            "tl_attendance_extra/static/src/dashboard/time_off_card.xml",
        ],
    },
    'installable': True,
    'application': False,
}

