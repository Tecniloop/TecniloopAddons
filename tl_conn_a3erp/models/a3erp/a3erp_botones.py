from odoo import models, fields, api
from datetime import datetime

class A3erpButtonImport(models.Model):
    _name = 'a3erp.button.import'
    _description = 'Pantalla para la importacion mediante botones.'

    
    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)    
    last_clientes_data = fields.Datetime(string='Última importación/replogs Clientes')
    last_dirent_data= fields.Datetime(string='Última importación/replogs Direcciones')
    last_proveed_data= fields.Datetime(string='Última importación/replogs Proveedores')
    last_contactos_data= fields.Datetime(string='Última importación/replogs Contactos')
    last_caracteristicas_data= fields.Datetime(string='Última importación/replogs Caracteristicas')
    last_docupago_data= fields.Datetime(string='Última importación/replogs Documentos Pago')
    last_formapago_data= fields.Datetime(string='Última importación/replogs Formas Pago')
    last_cargos_data= fields.Datetime(string='Última importación/replogs Cargos')
    last_alarmas_data= fields.Datetime(string='Última importación/replogs Alarmas')
    last_centrosc_data= fields.Datetime(string='Última importación/replogs CentrosCoste')
    last_opcionales_data= fields.Datetime(string='Última importación/replogs Opcionales')
    last_productos_data= fields.Datetime(string='Última importación/replogs Productos')
    last_idioma_data= fields.Datetime(string='Última importación/replogs Traducciones')
    last_refpro_data= fields.Datetime(string='Última importación/replogs Referencias Proveed')
    last_familias_data= fields.Datetime(string='Última importación/replogs Familias')
    # last_tarifas_data= fields.Datetime(string='Última importación/replogs Tarifas')
    # last_precesp_data= fields.Datetime(string='Última importación/replogs Precios Esp.')
    # last_descac_data= fields.Datetime(string='Última importación/replogs Descuentos AC')
    # last_descaf_data= fields.Datetime(string='Última importación/replogs Descuentos AF')
    # last_desccf_data= fields.Datetime(string='Última importación/replogs Descuentos CF')
    # last_descff_data= fields.Datetime(string='Última importación/replogs Descuentos FF')
    
    def _compute_display_name(self):
        for record in self:
            record.display_name = "Botones"

    @api.model
    def create(self, vals):
        #existing_record = self.search([('company_id','=',)], limit=1)
        existing_record = self.search([], limit=1)
        if existing_record:
            return existing_record
        return super(A3erpButtonImport, self).create(vals)

    @api.model
    def default_get(self, fields_list):
        res = super(A3erpButtonImport, self).default_get(fields_list)
        existing_record = self.search([], limit=1)
        if existing_record:
            return existing_record.read()[0]
        return res

    def button_clientes(self):
        self.last_clientes_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.clientes'].getall_clientes()
        else:
            self.env['a3erp.clientes'].get_rep_logs_clientes()
            self.env.ref('tl_conn_a3erp.ir_cron_proces_logs_clientes').method_direct_trigger()

    def button_productos(self):
        self.last_productos_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar_date':
            self.env['a3erp.productos'].getall_products_fecha(self.env.context.get('fecha_alta'))
        elif self.env.context.get('button_name') == 'importar_date_mod':
            self.env['a3erp.productos'].get_products_by_fecha_mod(self.env.context.get('fecha_mod'), self.env.context.get('campo'))
        elif self.env.context.get('button_name') == 'importar':
            self.env['a3erp.productos'].getall_products()
        else:
            self.env['a3erp.productos'].get_rep_logs_productos()
            self.env.ref('tl_conn_a3erp.ir_cron_proces_logs_productos').method_direct_trigger()
            
    def button_wizard_date(self):
        return {
            'name': 'Importar Productos según Fecha Alta/Mod',
            'type': 'ir.actions.act_window',
            'res_model': 'create.date.wizard',
            'view_mode': 'form',
            'target': 'new',
        }
 
    def button_dirent(self):
        self.last_dirent_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.dirent'].getall_dirent()
        else:
            self.env['a3erp.dirent'].get_rep_logs_dirent()
 
    def button_proveed(self):
        self.last_proveed_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.proveed'].getall_proveed()
        else:
            self.env['a3erp.proveed'].get_rep_logs_proveed()
 
    def button_contactos(self):
        self.last_contactos_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.contactos'].getall_contactos()
        else:
            self.env['a3erp.contactos'].get_rep_logs_contactos()
            self.env.ref('tl_conn_a3erp.ir_cron_proces_logs_clientes').method_direct_trigger()
    
    def button_caracteristicas(self):
        self.last_caracteristicas_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.caracteristicas'].getall_caracteristicas()
        else:
            self.env['a3erp.caracteristicas'].get_rep_logs_caracteristicas()
            self.env.ref('tl_conn_a3erp.ir_cron_proces_logs_caracteristicas').method_direct_trigger()
    
    def button_docupago(self):
        self.last_docupago_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.docupago'].getall_docpago()
        else:
            self.env['a3erp.docupago'].get_rep_logs_docpago()
            self.env.ref('tl_conn_a3erp.ir_cron_proces_logs_docupago').method_direct_trigger()

    def button_formapago(self):
        self.last_formapago_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.formapago'].getall_formapago()
        else:
            self.env['a3erp.formapago'].get_rep_logs_formapago()
            self.env.ref('tl_conn_a3erp.ir_cron_proces_logs_formapago').method_direct_trigger()

    def button_cargos(self):
        self.last_cargos_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.cargos'].getall_cargos()
        else:
            self.env['a3erp.cargos'].get_rep_logs_cargos()
            self.env.ref('tl_conn_a3erp.ir_cron_proces_logs_cargos').method_direct_trigger()

    def button_alarmas(self):
        self.last_alarmas_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.alarmas'].getall_alarmas()
        else:
            self.env['a3erp.alarmas'].get_rep_logs_alarmas()
            self.env.ref('tl_conn_a3erp.scheduled_action_process_alarmas').method_direct_trigger() # ALARMAS DE CLIENTES
            self.env.ref('tl_conn_a3erp.ir_cron_proces_logs_alarmas').method_direct_trigger() # ALARMAS DE PRODUCTOS

    def button_centrosc_1(self):
        self.last_centrosc_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.centrosc'].getall_centrosc(1)
        else:
            self.env['a3erp.centrosc'].get_rep_logs_centrosc(1)
            self.env.ref('tl_conn_a3erp.ir_cron_proces_logs_centrosc').method_direct_trigger()
    
    def button_centrosc_2(self):
        #self.last_centrosc_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.centrosc'].getall_centrosc(2)
    
    def button_centrosc_3(self):
        #self.last_centrosc_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.centrosc'].getall_centrosc(3)

    def button_opcionales(self):
        self.last_opcionales_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.opcionales'].getall_opcionales()
            self.env.ref('tl_conn_a3erp.ir_cron_proces_logs_opcionales').method_direct_trigger()
   
    def button_idiomas(self):
        self.last_idioma_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.idioma'].getall_traducciones()
        else:
            self.env['a3erp.idioma'].get_rep_logs_idioma()
   
    def button_refpro(self):
        self.last_refpro_data = fields.Datetime.now()
        self.env['a3erp.refpro'].get_rep_logs_refpro()
 
    def button_familias(self):
        self.last_familias_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.familias'].getall_familias()
        else:
            self.env['a3erp.familias'].get_rep_logs_familias()
            self.env.ref('tl_conn_a3erp.ir_cron_proces_logs_category').method_direct_trigger()

    def button_tarifas(self):
        self.last_tarifas_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.tarifas'].getall_tarifav()
        else:
            self.env['a3erp.tarifas'].get_rep_logs_tarifas()            
            self.env.ref('tl_conn_a3erp.ir_cron_proces_logs_tarifas').method_direct_trigger()

    def button_precios_esp(self):
        self.last_precesp_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.precios.esp'].getall_preciosesp()
        else:
            self.env['a3erp.precios.esp'].get_rep_logs_precios_esp()
            self.env.ref('tl_conn_a3erp.ir_cron_proces_logs_tarifas').method_direct_trigger()

    def button_descuent_ac(self):
        self.last_descac_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.descuentos.ac'].getall_descuentosac()
        else:
            self.env['a3erp.descuentos.ac'].get_rep_logs_descuentos_ac()
            self.env.ref('tl_conn_a3erp.ir_cron_proces_logs_tarifas').method_direct_trigger()
    
    def button_descuent_af(self):
        self.last_descaf_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.descuentos.af'].getall_descuentosaf()
        else:
            self.env['a3erp.descuentos.af'].get_rep_logs_descuentos_af()
    
    def button_descuent_ff(self):
        self.last_descaf_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.descuentos.ff'].getall_descuentosff()
        else:
            self.env['a3erp.descuentos.ff'].get_rep_logs_descuentos_ff()

    def button_descuent_cf(self):
        self.last_desccf_data = fields.Datetime.now()
        if self.env.context.get('button_name') == 'importar':
            self.env['a3erp.descuentos.cf'].getall_descuentoscf()
        else:
            self.env['a3erp.descuentos.cf'].get_rep_logs_descuentos_cf()
 
 