# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from ..web_service import *
import logging
from datetime import datetime, date, timedelta

_logger = logging.getLogger(__name__)

REPLOGS_PRODUCTOS = '{}/replog/getLogsArticulos'
PRODUCTOS_GETALL = '{}/articulo/getalloffset'
PRODUCTOS_GETALL_FECHA = '{}/articulo/getArtByFecAlta'

class A3erpProductos(models.Model):
    _name = 'a3erp.productos'
    _description = 'Productos de a3ERP.'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'fecha desc'
    _rec_name = 'descart'

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado') 
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])    
    
    #EL NOMBRE DEL CAMPO EL MISMO QUE EN A3ERP PERO EN MINUSCULA
    codart = fields.Char('Cod.Articulo')
    descart = fields.Char("Nombre")
    texto = fields.Text("Texto")
    prccoste = fields.Float("Coste")
    prcventa = fields.Float("Precio Venta")
    margen = fields.Float("Margen en Ventas %")
    codfamest = fields.Char("Categoria")
    tipiva = fields.Char("Tipo IVA")
    bloqueado = fields.Char('Bloqueado')
    es_venta = fields.Char('Es de Venta')
    obsoleto = fields.Char('Obsoleto')
    artpro = fields.Char('Referencia Proveedor')
    imagen = fields.Text('Imagen')
    analitica_1 = fields.Char('Analitica 1')    
    analitica_2 = fields.Char('Analitica 2')
    analitica_3 = fields.Char('Analitica 3')
    car1 = fields.Char('Car. 1')
    car2 = fields.Char('Car. 2')
    car3 = fields.Char('Car. 3')
    car4 = fields.Char('Car. 4')
    car5 = fields.Char('Car. 5')
    car6 = fields.Char('Car. 6')
    car7 = fields.Char('Car. 7')
    car8 = fields.Char('Car. 8')
    car9 = fields.Char('Car. 9')
    car10 = fields.Char('Car. 10')
    param1 = fields.Char('Param1')
    param2 = fields.Char('Param2')
    param3 = fields.Char('Param3')
    param4 = fields.Char('Param4')
    param5 = fields.Char('Param5')
    param6 = fields.Char('Param6')    
    param7 = fields.Char('Param7')    
    param8 = fields.Char('Param8')    
    param9 = fields.Char('Param9')    
    afecta_stock = fields.Char('Afecta Stock')    
    hay_num_serie = fields.Char('Hay Números de Serie')
    
    ##/!\ A PARTIR DE AQUI CAMPOS EXTRAS, NO ESTANDARES
    apen_mesprifac = fields.Integer("Meses Primera Facturación")
    apen_codartcont = fields.Char("Cod.Atrticulo Contrato")
    
    def get_rep_logs_productos(self):
        """Recibir los logs de productos de a3ERP."""
        
        self.env['a3erp.replogs'].get_replogs('productos', REPLOGS_PRODUCTOS, self._name, 'codart')
    
    def getall_products(self):
        """
        Recibir todos los productos de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('productos', PRODUCTOS_GETALL, self._name, 'codart', largeImport=True)

    def getall_products_fecha(self, fecha_alta):
        """
        Recibir todos los productos de a3ERP a partir de una fecha de alta determinada.
        """
        self.env['a3erp.replogs'].getall_records('productos', PRODUCTOS_GETALL_FECHA, self._name, 'codart', fecha_alta=fecha_alta)

REPLOGS_IDIOMA = '{}/replog/getLogsIdiomas'
GETALL_IDIOMAS = '{}/idiomas/getalloffset'

class A3erpIdioma(models.Model):
    _name = 'a3erp.idioma'
    _description = 'Traduccions de productos.'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'fecha desc'
    _rec_name = 'codart'

    #EL NOMBRE DEL CAMPO EL MISMO QUE EN A3ERP PERO EN MINUSCULA
    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])
        
    codart = fields.Char(string='Cod.Articulo a3ERP')
    descart = fields.Char(string='Nombre')
    texto = fields.Text(string='Descripción')
    codidioma = fields.Char(string='Idioma')
    
    def get_rep_logs_idioma(self):
        """Modelo para recibir los registros de IDIOMA."""
        
        self.env['a3erp.replogs'].get_replogs('idioma', REPLOGS_IDIOMA, self._name, 'codart', 'codidioma')
    
    def getall_traducciones(self):
        """
        Recibir todas las traducciones de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('idioma', GETALL_IDIOMAS, self._name, 'codart', 'codidioma', largeImport=True)

REPLOGS_REFPRO = '{}/replog/getLogsRefpro'
 
class A3erpRefPro(models.Model):
    _name = 'a3erp.refpro'
    _description = 'Referencias de Proveedor de a3ERP.'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'fecha desc'
    _rec_name = 'codart'

    #EL NOMBRE DEL CAMPO EL MISMO QUE EN A3ERP PERO EN MINUSCULA
    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])
        
    codpro = fields.Char(string='Cod.Proveedor a3ERP')
    codart = fields.Char(string='Cod.Articulo a3ERP')
    referencia = fields.Char(string='Referencia Proveedor')
    
    def get_rep_logs_refpro(self):
        """Modelo para recibir los registros de REFPRO."""
        
        self.env['a3erp.replogs'].get_replogs('refpro', REPLOGS_REFPRO, self._name, 'codart')

 
