
from odoo import models, fields, api, _
from ..web_service import *
from ..mapper_campos import TypeMapper
import requests, json, logging, re
from datetime import datetime, date, timedelta
from .. import create_log
from odoo.exceptions import UserError, ValidationError
from dateutil import parser

_logger = logging.getLogger(__name__)

CANON_TABLE = "APEN_CANONCAT"
CANON_MODULE_NAME = "tl_products_obligatorios"

class A3erpRepLogs(models.Model):
    _name = 'a3erp.replogs'    
    _description = "Recibir y Crear RepLogs a3ERP."
    
    def get_a3erp_record_data(self,tabla, url, company, key):
        """Metodo generico para recibir los datos de a3ERP del registro en concreto. ProductTempalate/ResPartner
            Args:
                tabla (string): Tabla objetivo.
                url (string): URL objetivo.
                company (object): Compañia del registro.
                key (string): Clave del registro.
            Returns:
                String: Devuelve la respuesta.
        """
        if not company.a3erp_active_company:
            return "Compañia Inactiva", False
        headers = {'Authorization': f'Bearer {company.a3erp_token}','Content-Type': 'application/json'}
        required_fields = self.env['a3erp.campos'].sudo().search([('table_name','=', tabla), ('field_use', 'in', ('a3erp-odoo', False)), ('company_id','in',(company.id, False))])
        if not required_fields:
            #create_log.create_log(self, "ERROR", "GET", self._name, False, False, f"No hay campos obligatorios para {tabla} informados, revisar.", company.id)
            return f"No hay campos obligatorios para {tabla} informados, revisar.", False
        
        campos = [field.a3erp_field_name for field in required_fields if field.a3erp_field_name]
        
        record_values = MensajeSolicitudGet(company.a3erp_company_id, campos, key)
        try:
            response = requests.get(url.format(company.a3erp_url), json=record_values.to_json(), verify=False, headers=headers, timeout=10)
        except Exception as e:
            _logger.info(format(e))
            return format(e), False            
        
        if response.status_code == 200: # CONSULTA SIN ERRORES
            return_message = MensajeRetorno = json.loads(response.text)
            if return_message['message'] == "Sin Errores":
                record_values = return_message['result']
                if record_values:
                    return record_values, required_fields
                else:
                    return "Registro no encontrado, Obsoleto o Bloqueado.", False
                
            elif return_message['message'] == "Error":
                return f"RepLogs: {return_message['result']}", False
                    
        elif response.status_code == 401: # CONSULTA NO AUTORIZADA
            return "Unauthorized: Usuario o Contraseña erroneos o Token Expirado.", False
                
        elif response.status_code == 400: # CONSULTA CON ERRORES DE ENVIO
            return_message = json.loads(response.text)['errors']
            error_key = next((key for key in return_message.keys() if key != 'mensaje'), None)
            return return_message[error_key][0], False
                
        return response.reason, False
    
    def get_replogs(self, tabla, url, modelo, campoClave, campoClave2 = False, **kwargs):
        """
        Recibir clientes/productos/contactos/tarifas modificados/creados/eliminados de a3ERP
        Args:
             tabla (String): Tabla para los campos necesarios.
            url (String): Url de consulta.
            modelo (String): Modelo donde crear los registros y consultar duplicados.
            campoClave (String): Campo clave para tener en cuenta los duplicados.
            campoClave2 (String): Campo clave 2 Opcional.  
        Raises:
            ValidationError: Campos obligatorios no encontrados.
        """
        companies = self.env['res.company'].search([('a3erp_active_company', '=', True)])
        for company in companies:
            headers = {'Authorization': f'Bearer {company.a3erp_token}','Content-Type': 'application/json'}
            required_fields = self.env['a3erp.campos'].sudo().search([('table_name','=', tabla), ('field_use', 'in', ('a3erp-odoo', False)), ('company_id','in',(company.id, False))])
            
            if not required_fields:
                create_log.create_log(self, "ERROR", "GET", self._name, False, False, f"No hay campos obligatorios para {tabla} informados, revisar.", company.id)
            else:   
                if tabla == 'caracteristicas' and not company.a3erp_canon_company or not company.module_is_installed(CANON_MODULE_NAME):
                    required_fields = self.not_include_canon_fields(required_fields)
                
                campos = [field.a3erp_field_name for field in required_fields if field.a3erp_field_name]
                if tabla == 'centrosc':
                    campos.append('APLINIVEL1')
                    campos.append('APLINIVEL2')
                    campos.append('APLINIVEL3')
                
                if tabla == 'tarifas':
                    campos.append('IDREG1')                    
                    campos.append('IDREG3')                    
                
                if tabla == 'familias':
                    campos.append('FICHERO')                    
                
                campos.append('FECHA') # FECHA DE EDICION
                campos.append('MOVIMIENTO') # SABER EL TIPO DE MOVIMIENTO (ALT/MOD/BOR)
                
                cola_state = MensajeSolicitudGet(company.a3erp_company_id, campos, datetime.now().strftime("%d/%m/%Y %H:%M:%S"))        
                response = requests.get(url.format(company.a3erp_url), json=cola_state.to_json(), verify=False, headers=headers, timeout=10)
                
                if response.status_code == 200: # CONSULTA SIN ERRORES
                        return_message = MensajeRetorno = json.loads(response.text)
                        
                        # ACTUALIZAR CAMPOS SI EL MENSAJE ES SIN ERRORES
                        if return_message['message'] == "Sin Errores":
                            lista_logs = return_message['result']
                            if lista_logs:
                                counted_records, error_records = self.insert_values(lista_logs, required_fields, modelo, campoClave, campoClave2, company, **kwargs)
                                create_log.create_log(self, "INFO", "GET", modelo, False, False, f"Compañia: {company.name} ; Registros: {counted_records}; Errores; {error_records}")
                            else:
                                continue
                        elif return_message['message'] == "Error":
                            create_log.create_log(self, "WARNING", "GET", modelo, False, False, f"RepLogs: {return_message['result']}", company.id)
                    
                elif response.status_code == 401: # CONSULTA NO AUTORIZADA
                    create_log.create_log(self, "ERROR", "GET", self._name, False, False, "Unauthorized: Usuario o Contraseña erroneos o Token Expirado.")
                
                elif response.status_code == 400: # CONSULTA CON ERRORES DE ENVIO
                    return_message = json.loads(response.text)['errors']
                    error_key = next((key for key in return_message.keys() if key != 'mensaje'), None)
                    create_log.create_log(self, "ERROR", "GET", modelo, False, False, return_message[error_key][0], company.id)
                
                else:
                    create_log.create_log(self, "ERROR", "GET" ,modelo, False, False, response.reason, company.id)
        
    def getall_records(self, tabla, url, modelo, campoClave, campoClave2 = False, largeImport = False, **kwargs):
        """
        Recibir todos los registros de la tabla como primera importacion.
        Args:
            tabla (String): Tabla para los campos necesarios.
            url (String): Url de consulta.
            modelo (String): Modelo donde crear los registros y consultar duplicados.
            campoClave (String): Campo clave para tener en cuenta los duplicados.
            campoClave2 (String): Campo clave 2 Opcional. 
        Raises:
            ValidationError: Campos obligatorios no encontrados.
        """
        #companies = self.env['res.company'].search([('a3erp_active_company', '=', True)])
        session = requests.Session()
        for company in self.env.company:
            headers = {'Authorization': f'Bearer {company.a3erp_token}','Content-Type': 'application/json'}        
            required_fields = self.env['a3erp.campos'].sudo().search([('table_name','=', tabla), ('field_use', 'in', ('a3erp-odoo', False)), ('company_id','in',(company.id, False))])
            
            if not required_fields:
                create_log.create_log(self, "ERROR", "GET", self._name, False, False, f"No hay campos obligatorios para {tabla} informados, revisar.", company.id)
                continue
            
            if tabla == 'caracteristicas' and not company.a3erp_canon_company or not company.module_is_installed(CANON_MODULE_NAME):
                required_fields = self.not_include_canon_fields(required_fields)

            campos = [field.a3erp_field_name for field in required_fields if field.a3erp_field_name]
            
            if tabla == 'centrosc':
                campos.append('APLINIVEL1')
                campos.append('APLINIVEL2')
                campos.append('APLINIVEL3')
            
            if tabla == 'familias':
                campos.append('FICHERO')  
                
            index = 0   
            try:                       
                while True:
                    if kwargs.get('fecha_alta'):
                        cola_state = MensajeSolicitudGet(company.a3erp_company_id, campos, str(kwargs.get('fecha_alta').date().strftime("%d/%m/%Y")))        
                    else:
                        cola_state = MensajeSolicitudGet(company.a3erp_company_id, campos, str(index))        
                        
                    response = session.get(url.format(company.a3erp_url), json=cola_state.to_json(), verify=False, headers=headers, timeout=10)
                        
                    if response.status_code == 200: # CONSULTA SIN ERRORES
                        return_message = MensajeRetorno = json.loads(response.text)
                                
                        # ACTUALIZAR CAMPOS SI EL MENSAJE ES SIN ERRORES
                        if return_message['message'] == "Sin Errores":
                            record_list = return_message['result']
                            if not record_list:
                                create_log.create_log(self, "INFO", "GET", modelo, False, False, f"Registros totales importados: {index}", company.id)
                                break
                                               
                            counted_records, error_records = self.insert_values(record_list, required_fields, modelo, campoClave, campoClave2, company, True, **kwargs)
                            
                            if largeImport:
                                create_log.create_log(self, "INFO", "GET", modelo, False, False, f"Importacion: {return_message['message']}; Registros: {counted_records}; Errores: {error_records}", company.id)
                                index += len(record_list)                            
                            else:
                                create_log.create_log(self, "INFO", "GET", modelo, False, False, f"Registros totales importados: {len(record_list)}", company.id)
                                break
                            
                        elif return_message['message'] == "Error":
                            create_log.create_log(self, "WARNING", "GET" , modelo, False, False, f"Importacion: {return_message['result']}", company.id)
                            break
                            
                    elif response.status_code == 401: # CONSULTA NO AUTORIZADA
                        create_log.create_log(self, "ERROR", "GET", self._name, False, False, "Unauthorized: Usuario o Contraseña erroneos o Token Expirado.", company.id)
                        break
                    
                    elif response.status_code == 400: # CONSULTA CON ERRORES DE ENVIO
                        return_message = json.loads(response.text)['errors']
                        error_key = next((key for key in return_message.keys() if key != 'mensaje'), None)
                        create_log.create_log(self, "ERROR", "GET" ,modelo, False, False, return_message[error_key][0], company.id)
                        break
                    
                    else:
                        create_log.create_log(self, "ERROR", "GET" ,modelo, False, False, response.reason, company.id)
                        break
                        
            except Exception as e:
                _logger.error(format(e))
                create_log.create_log(self, "ERROR", "GET", self._name, False, False, f"{format(e)}", company.id)
                break
        
    def insert_values(self, repList, required_fields, modelo, campoClave, campoClave2, company, getall = False, **kwargs):
        """
        Metodo para insertar los replogs que provinen de a3ERP y evitar duplicados segun campos clave.
        Tambien se utiliza para primer importacion de registros.        
        Args:
            repList (List): Lista de RepLogs.
            required_fields (List): Campos requeridos.
            modelo (String): Modelo donde crear el registro.
            campoClave (String): Campo clave 1 para consultar duplicados
            campoClave2 (String): Campo clave 2 para consultar duplicados
            getall (boolean): Si es True es importacion massiva, si no son replogs. 
        """
        register = False
        created_records = 0
        error_records = 0
        new_record = {}
        
        """COGER SOLO LAS CARACTERISTICAS DE ORGANIZACIÓN, CLIENTES, Y ARTICULOS"""
        if modelo == 'a3erp.caracteristicas':
            repList = self.control_exceptions(modelo, repList)
        
        """FILTRAR LOS DESCUENTOS SEGUN LLAMADA"""
        if getall and 'a3erp.descuentos' in modelo:
            repList = self.control_exceptions(modelo, repList)
        
        """FILTRAR SEGUN NIVEL DE CENTROS DE COSTE"""
        if modelo == 'a3erp.centrosc':
            repList = self.control_exceptions(modelo, repList, nivel = kwargs['nivel'])
        
        """DESCARTAS LOS PRODUCTOS QUE NO SON DE VENTA"""
        if modelo == 'a3erp.productos':
            repList = self.control_exceptions(modelo, repList)
        
        """DESCARTAR LAS FAMILIAS"""
        if modelo == 'a3erp.familias':
            repList = self.control_exceptions(modelo, repList)
        
        for record in repList:
            movimiento = record.get('MOVIMIENTO', 'ALT')
            
            """SI ESTAMOS EN TARIFAS Y EL REGISTRO SE HA BORRADO SOLO QUEREMOS EL CODART Y EL COD TARIFA"""
            if movimiento == 'BOR' and modelo == 'a3erp.tarifas':
                record = {k: v if v else None for k, v in record.items()}
                record['TARIFA'] = record.get('IDREG1', '').strip()
                record['CODART'] = record.get('IDREG3', '').strip()                           
            
            new_record = {}    
            if modelo == 'a3erp.centrosc':
                campoClave2 = 'nivelcentro'
                new_record['nivelcentro'] = kwargs['nivel']
            
            for field in required_fields: # AÑADIR CAMPOS DINAMICAMENTE SEGÚN LOS OBLIGATORIOS
                if not field.a3erp_field_name:
                    continue
                match = re.search(r'\sas\s*(\w+)$|\.(\w+)$|(\w+)$', field.a3erp_field_name, re.IGNORECASE)
                if match:
                    value = next((group for group in match.groups() if group), None)
                    if value and field.table_name == 'tarifas' and 'UNIDADES' in field.a3erp_field_name and record['UNIDADES']:
                        new_record[field.mapped_name] = record['UNIDADES'] if record['UNIDADES'] > 0 else 1
                    elif value and record[value]:
                        new_record[field.mapped_name] = record[value].strip() if 'TARIFA' in value or 'COD' in value else record[value]
                    else:
                        continue
  
                elif field.table_name == 'tarifas' and 'UNIDADES' in field.a3erp_field_name and record['UNIDADES']:
                    new_record[field.mapped_name] = record['UNIDADES'] if record['UNIDADES'] > 0 else 1
                elif record[field.a3erp_field_name]:
                    # SI SON CODIGO, QUITAR ESPACIOS
                    if 'COD' in field.a3erp_field_name or 'FAM' in field.a3erp_field_name: # HACER UN TRIM DE LOS CODIGOS
                        new_record[field.mapped_name] = record[field.a3erp_field_name].strip()
                    else:
                        new_record[field.mapped_name] = record[field.a3erp_field_name]
            
            if modelo == 'a3erp.familias':
                new_record['fichero'] = record.get('FICHERO')             
            
            new_record['company_id'] = company.id
            if not getall and campoClave in new_record:
                query_parts = [f"{campoClave} = '{new_record[campoClave]}'"]
                #new_record['fecha'] = datetime.strptime(record['FECHA'], '%Y-%m-%dT%H:%M:%S') - timedelta(hours=2)
                new_record['fecha'] = parser.parse(record['FECHA']) - timedelta(hours=2)
                new_record['movimiento'] = "ALT" if "COD" in record['MOVIMIENTO'] else record['MOVIMIENTO']
                query_parts.extend([
                    f"company_id = '{new_record['company_id']}'",
                    f"movimiento = '{new_record['movimiento']}'",
                    f"fecha = '{new_record['fecha']}'"
                ])
                if campoClave2:
                    query_parts.append(f"{campoClave2} = '{new_record[campoClave2]}'")
                        
                query = f"SELECT * FROM {modelo.replace('.', '_')} WHERE {' and '.join(query_parts)}"
        
                self.env.cr.execute(query)
                register = self.env.cr.fetchall()                
            
            else:
                new_record['movimiento'] = "ALT"
                new_record['fecha'] = datetime.now()
            
            if not register:
                try:
                    self.env[modelo].create(new_record)
                    self.env.cr.commit()
                    created_records +=1
                except Exception as e:
                    _logger.error(format(e))
                    create_log.create_log(self, "ERROR", "GET", self._name, False, False, f"{format(e)}: {new_record}", company.id)
                    error_records += 1
                    continue
        
        return created_records, error_records
    
    def control_exceptions(self, modelo, repList= False, **kwargs):
        """Controlar las excpeciones segun modelo.
        Args:
            modelo (String): Nombre del Modelo
            repList (bool, optional): Lista de Valores. Defaults to False.
        Returns:
            List: Lista modificada
        """
        # COGER SOLO LAS CARACTERISTICAS DE ORGANIZACIÓN, CLIENTES, Y ARTICULOS
        if modelo == 'a3erp.caracteristicas':
            repList = list(filter(lambda d: d['TIPCAR'] in ('A','C','O'), repList))
        
        #FILTRAR LAS DESCUENTOS SEGUN LLAMADA
        if 'a3erp.descuentos' in modelo:
            tipo_reg = modelo.split('.')[2].upper()
            repList = [record for record in repList if record['TIPREG'] == tipo_reg]
        
        #FILTRAR SEGUN NIVEL DE CENTROS DE COSTE
        if modelo == 'a3erp.centrosc' and 'nivel' in kwargs:
            mapeo_nivel = {
                1: "APLINIVEL1",
                2: "APLINIVEL2",
                3: "APLINIVEL3"
            }
            nivel = mapeo_nivel.get(kwargs['nivel'], 0)
            repList = list(filter(lambda d: d[nivel] == 'T', repList))
        
        # DESCARTAS LOS PRODUCTOS QUE NO SON DE VENTA
        if modelo == 'a3erp.productos':
            repList = [record for record in repList if record.get('ESVENTA', 'F') == 'T']
        
        # DESCARTAS LAS FAMILIAS QUE NO SON ESTADIS O DESCCLI
        if modelo == 'a3erp.familias':
            repList = [record for record in repList if record.get('FICHERO') in ('Estadis','DescCli')]
            
        return repList
    
    def not_include_canon_fields(self, fields):
        """Eliminar los campos CANON de la consulta de CARACTERISTICAS.
        Args:
            fields (List): Campos.
        Returns:
            List: Lista filtrada
        """
        filtered_filds = [obj for obj in fields if CANON_TABLE not in obj.a3erp_field_name]
        return filtered_filds

    
    def delete_replogs(self):
        """Eliminar los replogs de cada modelo auxiliar."""
        
        self.env.cr.execute("DELETE FROM a3erp_clientes WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_dirent WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_proveed WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_contactos WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_caracteristicas WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_docupago WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_formapago WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_cargos WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_alarmas WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_productos WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_idioma WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_familias WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_tarifas WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_precios_esp WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_descuentos_ac WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_descuentos_af WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_precios_esp WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_proveed WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_refpro WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_centrosc WHERE procesado = True")
        self.env.cr.execute("DELETE FROM a3erp_opcionales WHERE procesado = True")   
        self.env.cr.commit()
    
    def delete_mail_messages(self):
        """
            Elimina mensajes del chatter (mail_message) para modelos a3erp.*
            Solo elimina si:
            - El registro no tiene error
            - O si tiene error pero el mensaje tiene más de 4 días
        """
        
        self.env.cr.execute("""
            SELECT model 
            FROM ir_model 
            WHERE model LIKE 'a3erp.%' 
            ORDER BY model ASC
        """)
        values = self.env.cr.fetchall()

        excluded_models = (
            'a3erp.button.import',
            'a3erp.replogs',
            'a3erp.logs',
            'a3erp.campos',
        )

        for (model_name,) in values:
            if model_name in excluded_models:
                continue

            table_name = model_name.replace('.', '_')

            query = f"""
                DELETE FROM mail_message mm
                USING {table_name} m
                WHERE mm.model = %s
                  AND mm.res_id = m.id
                  AND (
                        m.error = FALSE
                        OR (m.error != FALSE AND mm.create_date < (NOW() - INTERVAL '4 days'))
                      )
            """
            self.env.cr.execute(query, (model_name,))
            self.env.cr.commit()  
                      
        
        