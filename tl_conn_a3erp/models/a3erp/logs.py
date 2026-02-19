from odoo import models, fields, api, _


class A3erpLogs(models.Model):
    _name = 'a3erp.logs'
    _order = 'create_date desc'
    _rec_name = 'type'
    _description = "Logs de las acciones"

    company_id = fields.Many2one(string='Compañia', comodel_name='res.company')
    type = fields.Char("Tipo", readonly=True)
    petition_name = fields.Selection(string='Petición',readonly=True, selection=[('GET', 'GET'), ('POST', 'POST'), ('POSTDOCUMENTO', 'POST-DOCUMENTO')])    
    model_name = fields.Char(string='Modelo', readonly=True)
    register_id = fields.Integer(string='ID Regsitro', readonly=True)
    register_name = fields.Char(string='Nombre Registro', readonly=True)        
    message = fields.Text("Message", readonly=True)
    

    def delete_logs(self):
        """Eliminar los logs cada periodo de tiempo."""
        
        self.env.cr.execute("DELETE FROM a3erp_logs")
        self.env.cr.commit()