# -*- coding: utf-8 -*-
from odoo import fields,models, api, _

class A3erpCampos(models.Model):
    _name = "a3erp.campos"
    _description = "Modelo para hacer las traducciones/mappeado de campos entre Odoo y A3erp "
    _rec_name = "table_name"
    _order = "sequence"
    
    active = fields.Boolean('Active', default=True)
    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    sequence = fields.Integer(default=5)
    table_name = fields.Selection(
        string="Tabla",
        selection=[
            ("clientes", "CLIENTES"),
            ("dirent", "DIRENT"),
            ("contactos", "CONTACTOS"),
            ("proveed", "PROVEEDORES"),
            ("refpro", "REFPRO"),
            ("productos", "PRODUCTOS"),
            ("familias", "FAMILIAS"),
            ("idioma", "IDIOMA"),
            ("cabeofev", "CABEOFEV"),
            ("cabepedv", "CABEPEDV"),
            ("cabepedc", "CABEPEDC"),
            ("lineofer", "LINEOFER"),
            ("tarifas", "TARIFAS"),
            ("precios_esp", "PRECIOSESP"),
            ("descuentos_ac", "DESCUENTOSAC"),
            ("descuentos_cf", "DESCUENTOSCF"),
            ("descuentos_fam", "DESCUENTOSAF"),
            ("descuentos_ff", "DESCUENTOSFF"),
            ("docupago", "DOCUPAGO"),
            ("formapag", "FORMAPAG"),
            ("caracteristicas", "CARACTERISTICAS"),
            ("cargos", "CARGOS"),
            ("alarmas", "ALARMAS"),
            ("centrosc", "CENTROSC"),
            ("opcionales", "OPCIONALES")
        ],
    )
    odoo_field_name = fields.Char(string='Nombre Odoo')
    mapped_name = fields.Char(string='Nombre Mappeo')
    a3erp_field_name = fields.Char(string='Nombre a3ERP')
    field_use = fields.Selection(string='Uso del campo', selection=[('a3erp-odoo', 'A3ERP->ODOO'), ('odoo-a3erp', 'ODOO->A3ERP')], help="Este campo sirve para diferenciar la direccion de su utilización, si no esta informado se utilizara para ambós sentidos.")
    relational_table = fields.Char(string='Tabla Relación', help="Si es un campo relacional hay que indicar el nombre del Modelo en Odoo.")
    table_code = fields.Char(string='Campo Relación', help="Indicar campo relacional del Modelo.")
    default_value = fields.Char(string='Valor por Defecto') 
    mandatory_field = fields.Boolean(string='Campo Obligatorio', help="Permite saber si es un campo esencial para el envio del registro.") 
    line_field_use = fields.Selection(
        string='Utilizar en',
        selection=[('purchase', 'Compras'), ('sale', 'Ventas')],
        help="Determinar si el campo de la linea se usa en Ventas, Compras o ambos."
    )

    _sql_constraints = [('unique_register', 'unique(table_name, odoo_field_name, a3erp_field_name, company_id)', 'Este registro ya existe.')]

    def get_required_values_receive(self, repValues, table):
        """
        Devuelve los campos requeridos por tabla. 
        Args:
            repValues (List): Lista de RepLogs
            table (String): Nombre de la tabla.
        Returns:
            Dict: diccionario de valores
        """
        company_ids = {rep.company_id.id for rep in repValues if rep.company_id}
        required_fields_by_company = {
            company_id: self.env['a3erp.campos'].search([
                ('table_name', '=', table),
                ('field_use', 'in', ('a3erp-odoo', False)),
                ('company_id', 'in', (company_id, False)),
                ('active', '=', True)
            ])
            for company_id in company_ids
        }
        return required_fields_by_company or None

    def get_required_values_send(self, company_id, table):
        """
        Devuelve los campos requeridos por tabla de envio a a3ERP. 
        Args:
            company_id: Id de la compañia del registro.
            table (String): Nombre de la tabla.
        Returns:
            Dict: diccionario de valores
        """
        required_fields_by_company = self.env['a3erp.campos'].search([
                ('table_name', '=', table),
                ('field_use', 'in', ('odoo-a3erp', False)),
                ('company_id', 'in', (company_id, False)),
                ('active', '=', True)
            ])
        return required_fields_by_company or None