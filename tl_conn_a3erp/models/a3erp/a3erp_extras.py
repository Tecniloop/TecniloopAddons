
from odoo import models, fields, api, _

REPLOGS_CARACTERISTICAS = '{}/replog/getLogsCaracteristicas'
CARACTERISTICAS_GETALL = '{}/caracteristicas/getall'

class A3erpCaracteristicas(models.Model):
    _name = 'a3erp.caracteristicas'
    _description = 'RepLog Caracteristicas a3ERP'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _rec_name = 'codcar'
    _order = 'numcar'

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])
    
    codcar = fields.Char(string='Cod.Carac')
    desccar = fields.Char(string='Descripción')
    numcar = fields.Integer(string='Núm. Carac.')
    tipcar = fields.Char(string='Tipo Carac.')
    codart_canon = fields.Char(string='Articulo Canon')    
    
    def get_rep_logs_caracteristicas(self):
        """
        Recibir caracteristicas de a3ERP.
        """
        self.env['a3erp.replogs'].get_replogs('caracteristicas', REPLOGS_CARACTERISTICAS, self._name, 'codcar', 'numcar')

    def getall_caracteristicas(self):
        """
        Recibir todas las caracteristicas de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('caracteristicas', CARACTERISTICAS_GETALL, self._name, 'codcar','numcar')

REPLOGS_DOCPAGO = '{}/replog/getLogsDocuPago'
DOCPAGO_GETALL= '{}/docupago/getall'

class A3erpDocupago(models.Model):
    _name = 'a3erp.docupago'
    _description = 'RepLog Documento Pago a3ERP'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _rec_name = 'descdoc'
    _order = 'docpag'

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])
    
    docpag = fields.Char(string='Codigo')
    descdoc = fields.Char(string='Descripción')
    obs = fields.Text(string='Observaciones')
    
    def get_rep_logs_docpago(self):
        """
        Recibir documentos de pago de a3ERP.
        """
        self.env['a3erp.replogs'].get_replogs('docupago', REPLOGS_DOCPAGO, self._name, 'docpag')
    
    def getall_docpago(self):
        """
        Recibir todos los documentos de pago de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('docupago', DOCPAGO_GETALL, self._name, 'docpag')

REPLOGS_FORMPAGO = '{}/replog/getLogsFormaPago'
FORMPAGO_GETALL =  '{}/formapago/getall'

class A3erpFormapago(models.Model):
    _name = 'a3erp.formapago'
    _description = 'RepLog Forma Pago a3ERP'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _rec_name = 'descfor'
    _order = 'forpag'

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])
    
    forpag = fields.Char(string='Codigo')
    descfor = fields.Char(string='Descripción')
    
    def get_rep_logs_formapago(self):
        """
        Recibir formas de pago de a3ERP.
        """
        self.env['a3erp.replogs'].get_replogs('formapag', REPLOGS_FORMPAGO, self._name, 'forpag')
    
    def getall_formapago(self):
        """
        Recibir todas las formas de pago de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('formapag', FORMPAGO_GETALL, self._name, 'forpag')

REPLOGS_CARGOS =  '{}/replog/getLogsCargos'
CARGOS_GETALL =  '{}/cargos/getall'

class A3erpCargos(models.Model):
    _name = 'a3erp.cargos'
    _description = 'RepLog Cargos a3ERP'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _rec_name = 'descripcion'
    _order = 'codigo'

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])
    
    idcargo = fields.Char(string='ID Cargo')
    codigo = fields.Char(string='Codigo')
    descripcion = fields.Char(string='Descripción')
    observaciones = fields.Text(string='Observaciones')    
    
    def get_rep_logs_cargos(self):
        """
        Recibir cargos de a3ERP.
        """
        self.env['a3erp.replogs'].get_replogs('cargos', REPLOGS_CARGOS, self._name, 'codigo')
    
    def getall_cargos(self):
        """
        Recibir todos los cargos de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('cargos', CARGOS_GETALL, self._name, 'codigo')

REPLOGS_ALARMAS =  '{}/replog/getLogsAlarma'
ALARMAS_GETALL =  '{}/alarmas/getall'

class A3erpAlarmas(models.Model):
    _name = 'a3erp.alarmas'
    _description = 'RepLog Alarmas a3ERP'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])
    
    codcli = fields.Char(string='Cliente')
    codartv = fields.Char(string='Articulo')
    alarmaofe = fields.Text(string='Alarma en Oferta')    
    
    @api.depends(lambda self: (self._rec_name,) if self._rec_name else ())
    def _compute_display_name(self):
        """Compute the value of the `display_name` field."""
        for record in self:
            record.display_name = f"{record.codcli if record.codcli else record.codartv}"
    
    def get_rep_logs_alarmas(self):
        """
        Recibir alarmas de a3ERP.
        """
        self.env['a3erp.replogs'].get_replogs('alarmas', REPLOGS_ALARMAS, self._name, 'codcli', 'codartv')
    
    def getall_alarmas(self):
        """
        Recibir todos las alarmas de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('alarmas', ALARMAS_GETALL, self._name, 'codcli', 'codartv')

REPLOGS_CENTROSC =  '{}/replog/getLogsCentrosC'
CENTROSC_GETALL =  '{}/centrosc/getalloffset'

class A3erpCentrosCoste(models.Model):
    _name = 'a3erp.centrosc'
    _description = 'RepLog Centros de Coste a3ERP'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _rec_name = 'codigo'
    _order = 'nivelcentro'

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])
    
    nivelcentro = fields.Integer(string='Nivel')    
    codigo = fields.Char(string='Codigo')
    descripcion = fields.Char(string='Descripcion')
    apen_centroln = fields.Char(string='Pregunta LN')
        
    def get_rep_logs_centrosc(self, nivel):
        """
        Recibir centrosc de a3ERP.
        """
        self.env['a3erp.replogs'].get_replogs('centrosc', REPLOGS_CENTROSC, self._name, 'codigo', nivel=nivel)
    
    def getall_centrosc(self, nivel):
        """
        Recibir los centrosc de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('centrosc', CENTROSC_GETALL, self._name, 'codigo', largeImport = True, nivel=nivel)

OPCIONALES_GETALL =  '{}/artopcionales/getall'

class A3erpOpcionales(models.Model):
    _name = 'a3erp.opcionales'
    _description = 'Productos Opcionales a3ERP'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _rec_name = 'cod_categoria'
    
    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado')    
    error = fields.Boolean(string='Error')    
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'), ('BOR','BOR')])
    
    cod_categoria = fields.Char(string='Categoria')
    cod_art_opcional = fields.Char(string='Art. Opcional')
        
    def getall_opcionales(self):
        """
        Recibir los producto opcionales de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('opcionales', OPCIONALES_GETALL, self._name, 'cod_categoria', 'cod_art_opcional', largeImport = False,)

REPLOGS_FAMILIAS = '{}/replog/getLogsFamiliaArtEstadis'
FAMILIAS_GETALL = '{}/familias/getalloffset'

class A3erpFamilias(models.Model):
    _name = 'a3erp.familias'
    _description = 'Familias a3ERP'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'fecha desc'
    _rec_name = 'codigo'

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company', default=lambda self: self.env.company)
    procesado = fields.Boolean(string='Procesado')
    error = fields.Boolean(string='Error')
    fecha = fields.Datetime(string='Fecha Movimiento')
    movimiento = fields.Selection(string='Movimiento', selection=[('MOD', 'MOD'), ('ALT', 'ALT'),('BOR','BOR')])
    
    codigo = fields.Char('Cod.Familia')
    nombre = fields.Char("Nombre")
    fichero = fields.Char("Fichero")    
    
    def get_rep_logs_familias(self):
        """Recibir los logs de familias de a3ERP."""
        
        self.env['a3erp.replogs'].get_replogs('familias', REPLOGS_FAMILIAS, self._name, 'codigo')
        
    def getall_familias(self):
        """
        Recibir todas las familias de a3ERP.
        """
        self.env['a3erp.replogs'].getall_records('familias', FAMILIAS_GETALL, self._name, 'codigo', largeImport=True)