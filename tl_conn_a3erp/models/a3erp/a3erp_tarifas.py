# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from ..web_service import *
import logging

REPLOGS_TARIFAS = '{}/replog/getLogsTarifas'
REPLOGS_PRECIOSESP = '{}/replog/getLogsPreciosEsp'
REPLOGS_DESCUENTOSAC = '{}/replog/getLogsDescuentosAC' #CLIENTE - ARTICULO
REPLOGS_DESCUENTOSAF = '{}/replog/getLogsDescuentosAF' #ARTICULO - FAMILIA CLIENTE
REPLOGS_DESCUENTOSCF = '{}/replog/getLogsDescuentosCF' #CLIENTE - FAMILIA ARTICULO
REPLOGS_DESCUENTOSFF = '{}/replog/getLogsDescuentosFF' #FAMILIA CLIENTE - FAMILIA ARTICULO

TARIFA_GETALL = '{}/tarifav/getalloffset'
PRECIOSESP_GETALL = '{}/prcesp/getalloffset'
DESCUENTO_GETALL = '{}/descuento/getalloffset'
DESCUENTOCF_GETALL = '{}/descuento/getalloffsetDescArt'

class A3erpTarifas(models.Model):
    _name = 'a3erp.tarifas'
    _description = 'Tarifas de a3ERP.'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'fecha desc'
    _rec_name = 'desctarifa'

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Producto Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])    
    
    #EL NOMBRE DEL CAMPO EL MISMO QUE EN a3ERP PERO EN MINUSCULA
    tarifa = fields.Char("Cod. Tarifa")
    desctarifa = fields.Char("Nombre Tarifa")
    codart = fields.Char('Cod.Articulo')
    precio = fields.Float("Precio")
    unidades = fields.Integer("Unidades")
    codmon = fields.Char("Moneda")    
    
    def get_rep_logs_tarifas(self):
        """Recibir los logs de tarifas de a3ERP."""
        
        self.env['a3erp.replogs'].get_replogs('tarifas', REPLOGS_TARIFAS, self._name, 'tarifa', 'codart')
        
    def getall_tarifav(self):
        """
        Recibir todas las tarifas de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('tarifas', TARIFA_GETALL, self._name, 'tarifa', 'codart', largeImport=True)

class A3erpPreciosEsp(models.Model):
    _name = 'a3erp.precios.esp'
    _description = 'Precios especiales de a3ERP.'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'fecha desc'
    _rec_name = 'codcli'

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Producto Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])    
    
    #EL NOMBRE DEL CAMPO EL MISMO QUE EN a3ERP PERO EN MINUSCULA
    codcli = fields.Char("Cod. Cliente")
    codart = fields.Char('Cod.Articulo')
    precio = fields.Float("Precio")
    unidades = fields.Integer("Unidades")
    codmon = fields.Char("Moneda")    
    
    def get_rep_logs_precios_esp(self):
        """Recibir los logs de precios especiales de a3ERP."""
        
        self.env['a3erp.replogs'].get_replogs('precios_esp', REPLOGS_PRECIOSESP, self._name, 'codcli', 'codart')
    
    def getall_preciosesp(self):
        """
        Recibir todos los precios especiales de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('precios_esp', PRECIOSESP_GETALL, self._name, 'codcli', 'codart', largeImport=True)
        
class A3erpDescuentosAC(models.Model):
    _name = 'a3erp.descuentos.ac'
    _description = 'Descuentos Articulo-Cliente a3ERP.'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'fecha desc'
    _rec_name = 'codcli'

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Producto Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])    
    
    #EL NOMBRE DEL CAMPO EL MISMO QUE EN a3ERP PERO EN MINUSCULA
    codcli = fields.Char("Cod. Cliente")
    codart = fields.Char('Cod. Articulo')
    desc1 = fields.Float('Descuento 1')
    desc2 = fields.Float('Descuento 2')
    unidades = fields.Integer("Unidades")
    tipreg = fields.Char("Tipo Registro")
    
    def get_rep_logs_descuentos_ac(self):
        """Recibir los logs de descuentos de a3ERP."""
        
        self.env['a3erp.replogs'].get_replogs('descuentos_ac', REPLOGS_DESCUENTOSAC, self._name, 'codcli', 'codart')
    
    def getall_descuentosac(self):
        """Recibir todos los descuentos AC"""
        
        self.env['a3erp.replogs'].getall_records('descuentos_ac', DESCUENTO_GETALL, self._name, 'codcli', 'codart', largeImport=True) 

class A3erpDescuentosAF(models.Model):
    _name = 'a3erp.descuentos.af'
    _description = 'Descuentos por Articulo-Familia Cliente a3ERP.'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'fecha desc'
    _rec_name = 'famcli'

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Producto Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])    
    
    #EL NOMBRE DEL CAMPO EL MISMO QUE EN a3ERP PERO EN MINUSCULA
    codart = fields.Char('Cod. Articulo')
    famcli = fields.Char('Familia Client')    
    descfam = fields.Char('Descripción Familia')    
    desc1 = fields.Float('Descuento 1')
    desc2 = fields.Float('Descuento 2')
    unidades = fields.Integer("Unidades")
    tipreg = fields.Char("Tipo Registro")
    
    def get_rep_logs_descuentos_af(self):
        """Recibir los logs de AF de a3ERP."""
        
        self.env['a3erp.replogs'].get_replogs('descuentos_fam', REPLOGS_DESCUENTOSAF, self._name, 'codart', 'famcli')
    
    def getall_descuentosaf(self):
        """Recibir todos los descuentos AF"""
        
        self.env['a3erp.replogs'].getall_records('descuentos_fam', DESCUENTO_GETALL, self._name, 'codcli', 'famcli', largeImport=True)
        
class A3erpDescuentosCF(models.Model):
    _name = 'a3erp.descuentos.cf'
    _description = 'Descuentos por Articulo-Familia Cliente a3ERP.'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'fecha desc'
    _rec_name = 'famart'

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Producto Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')]) 
    
    #EL NOMBRE DEL CAMPO EL MISMO QUE EN a3ERP PERO EN MINUSCULA
    codcli = fields.Char(string='Cod.Cliente')
    famart = fields.Char(string='Familia Artiulo (Categoria)')
    descfam = fields.Char('Descripción Familia')    
    desc1 = fields.Float('Descuento 1')
    desc2 = fields.Float('Descuento 2')
    unidades = fields.Integer("Unidades")
    tipreg = fields.Char("Tipo Registro")

    def get_rep_logs_descuentos_cf(self):
        """Recibir los logs de CF de a3ERP."""
        
        self.env['a3erp.replogs'].get_replogs('descuentos_cf', REPLOGS_DESCUENTOSCF, self._name, 'codcli', 'famart')
    
    def getall_descuentoscf(self):
        """Recibir todos los descuentos CF"""
        
        self.env['a3erp.replogs'].getall_records('descuentos_cf', DESCUENTOCF_GETALL, self._name, 'codcli', 'famart', largeImport=True) 
        
class A3erpDescuentosFF(models.Model):
    _name = 'a3erp.descuentos.ff'
    _description = 'Descuentos por Familia Articulo-Familia Cliente a3ERP.'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'fecha desc'
    _rec_name = 'famcli'

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Producto Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')]) 
    
    famcli = fields.Char(string='Familia Cliente')
    famart = fields.Char(string='Familia Artiulo (Categoria)')
    descfam = fields.Char('Descripción Familia ')    
    desc1 = fields.Float('Descuento 1')
    desc2 = fields.Float('Descuento 2')
    unidades = fields.Integer("Unidades")
    tipreg = fields.Char("Tipo Registro")

    def get_rep_logs_descuentos_ff(self):
        """Recibir los logs de FF de a3ERP."""
        
        self.env['a3erp.replogs'].get_replogs('descuentos_ff', REPLOGS_DESCUENTOSFF, self._name, 'famcli', 'famart')
    
    def getall_descuentosff(self):
        """Recibir todos los descuentos FF"""
        
        self.env['a3erp.replogs'].getall_records('descuentos_ff', DESCUENTOCF_GETALL, self._name, 'famcli', 'famart', largeImport=True) 
