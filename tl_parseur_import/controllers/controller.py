
from odoo import http
from odoo.http import request, Response
import json
import logging


_logger = logging.getLogger(__name__)

class ParseurController(http.Controller):
    
    @http.route('/get/parseur/data', type='jsonrpc', auth='public', methods=['POST'], csrf=False)
    def get_parseur_data(self,**kw):
   
        data = request.httprequest.data.decode('utf-8').strip()
        if not data or data in ["{}", "[]", "{\r\n\r\n}"]:
            return {'status':'error', 'message':'No se han enviado datos'}   
        
        json_data = json.loads(data)
        values = json_data['params'] if 'params' in json_data else json_data
        #values = json.loads(json_data['params']['value'])
        try:
            record = request.env['parseur.order'].sudo().create_record(values)
        except Exception as e:
            _logger.error(f'Error creando el registro: {format(e)}')
            return {'status':'error', 'message':f'Error creando el registro: {format(e)}'}             
        
        _logger.info("Received data: %s", values)
        
        return {'status':'sucess', 'message':f'Registro creado {record.id}'}             
