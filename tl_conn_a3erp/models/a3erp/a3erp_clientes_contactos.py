# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import MissingError, UserError, ValidationError
from ..web_service import *
from ..mapper_campos import TypeMapper
import requests, json, logging
from datetime import datetime, date, timedelta
from .. import create_log

REPLOGS_CLIENTES = '{}/replog/getLogsCliente'
CLIENTES_GETALL = '{}/clientes/getalloffset'
CLIENTE_GETBYCODE = "{}/clientes/getbycode"

class A3erpClientes(models.Model):
    _name = 'a3erp.clientes'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _description = 'RepLog Clientes de a3ERP.'
    _order = 'fecha desc'
    _rec_name = 'nomcli'
    
    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])    
    
    
    codcli = fields.Char(string='Cod. Cliente')
    nomcli = fields.Char(string="Nombre")
    alias = fields.Char(string="Alias")
    dircli1 = fields.Char(string='Dirección')
    codpais = fields.Char(string='Pais')
    nifcli = fields.Char(string='VAT')
    codprovi = fields.Char(string='Provincia')
    pobcli = fields.Char(string='Población')
    dtocli = fields.Char(string='Codigo Postal')
    telcli = fields.Char(string='Telefono')
    telcli2 = fields.Char(string='Mobil')
    e_mail = fields.Char(string='Email')
    codidioma = fields.Char(string='Idioma')
    paginaweb = fields.Char(string='Website')
    tarifa = fields.Char(string='Cod. Tarifa')
    famclidesc = fields.Char(string='Cod. Familia Desc.')
    bloqueado = fields.Char(string='Bloqueado')
    obsoleto = fields.Char(string='Obsoleto')
    docpag = fields.Char(string='Doc. Pago')
    forpag = fields.Char(string='Forma Pago')
    cod_rep = fields.Char(string='Representante')
    exento_canon = fields.Char(string='Exento Canon')
    car1_org = fields.Char(string='Carac. Org. 1')
    car2_org = fields.Char(string='Carac. Org. 2')
    car3_org = fields.Char(string='Carac. Org. 3')
    car4_org = fields.Char(string='Carac. Org. 4')
    car5_org = fields.Char(string='Carac. Org. 5')
    car6_org = fields.Char(string='Carac. Org. 6')
    car7_org = fields.Char(string='Carac. Org. 7')
    car8_org = fields.Char(string='Carac. Org. 8')
    car9_org = fields.Char(string='Carac. Org. 9')
    car10_org = fields.Char(string='Carac. Org. 10')
    car1 = fields.Char(string='Car. 1')
    car2 = fields.Char(string='Car. 2')
    car3 = fields.Char(string='Car. 3')
    car4 = fields.Char(string='Car. 4')
    car5 = fields.Char(string='Car. 5')
    car6 = fields.Char(string='Car. 6')
    car7 = fields.Char(string='Car. 7')
    car8 = fields.Char(string='Car. 8')
    car9 = fields.Char(string='Car. 9')
    car10 = fields.Char(string='Car. 10')
    param1 = fields.Char(string='Param1')
    param2 = fields.Char(string='Param2')
    param3 = fields.Char(string='Param3')
    param4 = fields.Char(string='Param4')
    param5 = fields.Char(string='Param5')
    param6 = fields.Char(string='Param6')    
    param7 = fields.Char(string='Param7')    
    param8 = fields.Char(string='Param8')    
    param9 = fields.Char(string='Param9')  
    ##/!\ A PARTIR DE AQUI CAMPOS EXTRAS, NO ESTANDARES    
    
    _sql_constraints = [('unique_register', 'unique(movimiento, fecha, codcli)', 'Este registro ya existe.')]
    
    def get_rep_logs_clientes(self):
        """Recibir clientes modificados/creados/eliminados de a3ERP"""
        #IMPORTAR REPLOGS TARIFAS ANTES QUE CLIENTES
        #self.env['a3erp.tarifas'].get_rep_logs_tarifas() OBSOLETO, TARIFAS YA NO SE ACTUALIZAN
        
        self.env['a3erp.replogs'].get_replogs('clientes', REPLOGS_CLIENTES, self._name, "codcli")
    
    def getall_clientes(self):
        """
        Recibir todos los clientes de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('clientes', CLIENTES_GETALL, self._name, 'codcli', largeImport=True)
    
    def get_field_by_client(self, listaCampos, codCli, company_id):
        """Hacer un GET a un client en concreto de a3ERP.
        Args:
            listaCampos (List): Listado de campos que queremos consultar.
            codCli (String): Codigo del cliente (CODCLI)
        Returns:
            Object: Devuelve la respuesta o False.
        """
        headers = {'Authorization': f'Bearer {company_id.a3erp_token}','Content-Type': 'application/json'}
        
        cola_state = MensajeSolicitudGet(company_id.a3erp_company_id, listaCampos, cuadrar(codCli))        
        response = requests.get(CLIENTE_GETBYCODE.format(company_id.a3erp_url), json=cola_state.to_json(), verify=False, headers=headers, timeout=10)
        if response.status_code == 200: # CONSULTA SIN ERRORES
            return_message = MensajeRetorno = json.loads(response.text)  
                    
            # ACTUALIZAR CAMPOS SI EL MENSAJE ES SIN ERRORES
            if return_message['message'] == "Sin Errores":
                codTarifa = return_message['result'][0]
                return codTarifa, False
                        
            elif return_message['message'] == "Error":
                create_log.create_log(self, "WARNING", "POST" ,self._name, False, False, return_message['result'], company_id.id)
                return "Error", return_message['result']
            
        elif response.status_code == 401: # CONSULTA NO AUTORIZADA
            create_log.create_log(self, "ERROR", "GET", self._name, False, False, "Unauthorized: Usuario o Contraseña erroneos o Token Expirado.")
            return "Unauthorized", False
            
        elif response.status_code == 400: # CONSULTA CON ERRORES DE ENVIO
            return_message = json.loads(response.text)['errors']
            error_key = next((key for key in return_message.keys() if key != 'mensaje'), None)
            create_log.create_log(self, "ERROR", "POST" ,self._name, False, False, return_message[error_key][0], company_id.id)
            return "Error", return_message[error_key][0]

REPLOGS_DIRENT = '{}/replog/getLogsDirent'
DIRENT_GETALL = '{}/dirent/getalloffset'

class A3erpDireccionesEntrega(models.Model):
    _name = 'a3erp.dirent'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _description = 'RepLog Direcciones de entrega de Clientes a3ERP.'
    _order = 'fecha desc'
    _rec_name = 'noment'

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])

    
    iddirent = fields.Char(string='ID.Direccion')
    noment = fields.Char(string='Nom')    
    codcli = fields.Char(string='Cod.Cliente')
    codpais = fields.Char(string='Cod.Pais')
    codprovi = fields.Char(string='Cod.Provincia')
    dirent1 = fields.Char(string='Direccion 1')
    dirent2 = fields.Char(string='Direccion 2')
    dtoent = fields.Char(string='Cod.Postal')
    pobent = fields.Char(string='Poblacion')
    telent1 = fields.Char(string='Telefono 1')   
    telent2 = fields.Char(string='Telefono 2')    
    email = fields.Char(string='Email')
    obsoleto = fields.Char(string='Obsoleto')
    defecto = fields.Char(string='Por Defecto')
    
    def get_rep_logs_dirent(self):
        """Recibir direcciones de entrega de clientes de a3ERP"""
        
        self.env['a3erp.replogs'].get_replogs('dirent', REPLOGS_DIRENT, self._name, "iddirent")
    
    def getall_dirent(self):
        """
        Recibir todas las direcciones de entrega de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('dirent', DIRENT_GETALL, self._name, 'iddirent', largeImport=True)

REPLOGS_PROVEED = '{}/replog/getLogsProveed'
PROVEED_GETALL = '{}/proveedores/getalloffset'

class A3erpProveedores(models.Model):
    _name = 'a3erp.proveed'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _description = 'RepLog Proveedores de a3ERP.'
    _order = 'fecha desc'
    _rec_name = 'nompro'
    
    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])    
    
    obsoleto = fields.Char(string='Obsoleto')
    codpro = fields.Char(string='Cod. Proveedor')
    nompro = fields.Char(string="Nombre")
    nifpro = fields.Char(string='NIF')
    alias = fields.Char(string='Alias')
    
    def get_rep_logs_proveed(self):
        """Recibir proveedores modificados/creados/eliminados de a3ERP"""
        
        self.env['a3erp.replogs'].get_replogs('proveed', REPLOGS_PROVEED, self._name, "codpro")
    
    def getall_proveed(self):
        """
        Recibir todos los proveedores de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('proveed', PROVEED_GETALL, self._name, 'codpro', largeImport=True)

REPLOGS_CONTACTOCLIENTE = '{}/replog/getLogsContactosRelacionCliente'
CONTACTOS_GETALL = '{}/contactos/getalloffset'
REPLOGS_CONTACTOS = '{}/replog/getLogsContactos'
             
class A3erpContactos(models.Model):
    _name = 'a3erp.contactos'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _description = 'RepLog Contactos de a3ERP.'
    _order = 'fecha desc'
    _rec_name = 'nombre'
    
    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])
    
    
    codcli = fields.Char(string="Cod. Cliente")
    idcontacto = fields.Char(string="ID Contacto")
    idcontactorelacion = fields.Char(string="ID Contacto Relacion")
    tipoentidad = fields.Char(string="Tipo Entidad")
    idcargo = fields.Char(string="ID Cargo")
    nombre = fields.Char(string="Nombre")
    enviar_email = fields.Boolean(string='Permitir Publicidad')    
    e_mail = fields.Char(string='Email')
    dir1 = fields.Char(string='Dirección 1')
    dir2 = fields.Char(string='Dirección 2')
    codpais = fields.Char(string='Pais')
    codprovi = fields.Char(string='Provincia')
    poblacion = fields.Char(string='Población')
    telefono1 = fields.Char(string='Telefono')
    telefono2 = fields.Char(string='Mobil')
    obsoleto = fields.Integer(string='Obsoleto')
    
    ##/!\ A PARTIR DE AQUI CAMPOS EXTRAS, NO ESTANDARES                    
            
    def get_rep_logs_contactos(self):
        """
        Recibir contactos modificados/creados/eliminados de a3ERP
        """
        self.env['a3erp.replogs'].get_replogs('contactos', REPLOGS_CONTACTOCLIENTE, self._name, 'idcontacto')
        
    def getall_contactos(self):
        """
        Recibir todos los contactos de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('contactos', CONTACTOS_GETALL, self._name, 'idcontacto', largeImport=True)
    
