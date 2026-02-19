from odoo.tools import convert_file

def post_init_insert_a3erp_required_fields(cr):
    convert_file(cr, 'tl_conn_a3erp', 'data/a3erp.campos.csv', None, mode='init', noupdate=True, kind='init')
    