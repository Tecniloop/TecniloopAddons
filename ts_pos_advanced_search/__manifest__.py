# -*- coding: utf-8 -*-
#############################################################################
#
#    Techvaria Solutions Pvt. Ltd.
#
#    Copyright (C) 2025-Techvaria Solutions(<https://techvaria.com>)
#    Author: Techvaria Solutions Pvt. Ltd.(info@techvaria.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################

{
    'name': 'POS Advanced Search',
    'version': '19.0.1.0.0',
    'category': 'Sales/Point of Sale',
    'summary': 'The module introduces an intuitive search feature for POS, enabling users to perform advanced searches using multiple keywords.',
    'author': 'Techvaria',
    'company': 'Techvaria',
    'maintainer': 'Techvaria',
    'website': "https://techvaria.com",
    "depends": ['point_of_sale'],
    "assets": {
        "point_of_sale._assets_pos": [
            "ts_pos_advanced_search/static/src/store/pos_store.js"
        ],
    },
    'images': [
        'static/description/screen.jpg',
    ],
    'license': 'AGPL-3',
    'installable': True,
    'auto_install': False,
}
