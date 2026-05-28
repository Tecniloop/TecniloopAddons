import logging

_logger = logging.getLogger(__name__)

def create_log(self, log_type, peticion, model_id, register_id, register_name, message, company_id=None):
    """ Crear log en pantalla de logs.
    Args:
        log_type (String): Tipo de Log [ERROR, INFO, WARNING]
        peticion (String): Tipo de peticion
        model_id (String): Nombre del modelo
        register_id (String): Registro
        register_name (String): Nombre Registro
        message (String): Mensaje
    Raises:
        ValueError: Error
    """
    try:
        self.env['a3erp.logs'].sudo().create({
            'type': log_type if log_type else None,
            'petition_name': peticion if peticion else None,
            'model_name': model_id if model_id else None,
            'register_id': register_id if register_id else None,
            'register_name': register_name if register_name else None,
            'message': message if message else None,
            'company_id': company_id if company_id else None,
        })
        _logger.info("LOG CREATED SUCCESSFULLY")
    except Exception as e:
        raise ValueError(e)
