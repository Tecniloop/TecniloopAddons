"Clases para la solicitudes al Web Service"
from datetime import datetime, date
from odoo.exceptions import MissingError, UserError, ValidationError
import json

ENTIDADCLIENTES = "CLIENTES"
ENTIDADOFERTA = "OFERTAS"
ENTIDADPEDIDOS = "PEDIDOS"
ENTIDADPEDIDOSC = "PEDIDOSC"
ENTIDADALBARANESC = "ALBARANESC"
ENTIDADOFERTACLIENTE = "CLIENTES_OFERTAS"
ENTIDADPEDIDOSCLIENTE = "CLIENTES_PEDIDOS"
ENTIDADCONTACTOS = "CONTACTOS"
ENTIDADARTICULOS = "ARTICULO"
ENTIDADREFERENCIAS = "REFPRO"
ENTIDADIDIOMAS = "IDIOMAS"
ENTIDADDIRECCIONES = "DIRENT"

class MensajeSolicitudPostDocumento:
    def __init__(self, idEmpresa, tipoPeticion, entidad, documento):
        self.idempresa = idEmpresa
        self.tipopeticion = tipoPeticion
        self.entidadpeticion = entidad
        self.documento = documento
    
class Documento:
    def __init__(self, cabecera, lineas):
        self.cabecera_documento = cabecera
        self.lineas_documento = lineas
    
class LoginModel:
    def __init__(self, user, pwd):
        self.User = user
        self.Pwd = pwd
    
    def to_json(self):
        return {
            "User": self.User,
            "Pwd": self.Pwd
        }

class MensajeSolicitudPost:
    def __init__(self, idEmpresa, tipoPeticion, entidad, parametros):
        self.idempresa = idEmpresa
        self.tipopeticion = tipoPeticion
        self.entidadpeticion = entidad
        self.parametros = parametros
        
    def to_json(self):
        parametros = []
        for parametro in self.parametros:
            # parametros.append({"campo": parametro.campo,"valor": str(parametro.valor),"tipo": parametro.tipo})
            parametros.append(parametro.to_json())

        return {
            "idempresa": self.idempresa,
            "tipopeticion": self.tipopeticion,
            "entidadpeticion": self.entidadpeticion,
            "parametros": parametros
        }    

class Parametro:
    def __init__(self, campo, valor, tipo):
        self.campo = campo
        self.valor = valor
        self.tipo = tipo
    
    def to_json(self):
        return {
            "campo": self.campo,
            "valor": str(self.valor).replace('"','\"').replace('″','\"'),
            "tipo": self.tipo
        }
    
class MensajeSolicitudGet:
    def __init__(self, idEmpresa, campos, clave, clavesExtra=[]):
        self.idempresa = idEmpresa
        self.campos = campos
        self.clavetabla = clave
        self.clavesExtra = clavesExtra
    
    def to_json(self):
        campos = []
        # for campo in self.campos:
        #     campos.append({
        #         "campo": campo.campo,
        #         "valor": campo.valor,
        #         "tipo": campo.tipo
        #     })

        return {
            "idempresa": self.idempresa,
            "clavetabla": self.clavetabla,
            "campos": self.campos,
            "clavesExtra": self.clavesExtra,
        }

class MensajeSolicitudGetParams:
    
    def __init__(self, idEmpresa, parametros):
        self.idempresa = idEmpresa
        self.parametros = parametros
    
    def to_json(self):
        parametros = []
        for parametro in self.parametros:
            parametros.append(parametro.to_json())

        return {
            "idempresa": self.idempresa,
            "parametros": parametros
        }
        
class MensajeRetorno:
    def __init__(self):
        self.success = ""
        self.message = ""
        self.result = ""
    
    def __init__(self, success, mensaje, resultado):
        self.success = success
        self.message = mensaje
        self.result = resultado

class AltaDocumento:
    
    def __init__(self, parametros, documento):
      self.parametros = parametros
      self.documento = documento

class MensajeSolicitudPostAltaYDocumento:
    def __init__(self, idEmpresa, tipoPeticion, entidad, altaDocumento):
      self.idempresa = idEmpresa
      self.tipopeticion = tipoPeticion
      self.entidadpeticion = entidad
      self.altaYDocumento = altaDocumento

def mensaje_solicitud_post_alta_y_documento_to_json(mensaje):
    """Convierte un objeto MensajeSolicitudPostAltaYDocumento a JSON."""
    json_data = {
        "idempresa": mensaje.idempresa,
        "tipopeticion": mensaje.tipopeticion,
        "entidadpeticion": mensaje.entidadpeticion,
        "AltaYDocumento": alta_documento_to_json(mensaje.altaYDocumento)
    }
    return json_data

def alta_documento_to_json(alta_doc):
    """Convierte un objeto AltaDocumento a JSON."""
    json_data = {
        "parametros": [parametro.to_json() for parametro in alta_doc.parametros],
        "documento": convertir_documento_a_json(alta_doc.documento) if alta_doc.documento else None
    }
    return json_data
       
def post_documento_to_json(mensaje):
    """Convierte un objeto MensajeSolicitudPostDocumento a JSON.
    Args:
        mensaje: Recibe el objeto PostDocument.
    Return:
        Devuelve el objeto en formato json.
    """
    json_data = {}

    # Convertir propiedades simples
    json_data["idempresa"] = mensaje.idempresa
    json_data["tipopeticion"] = mensaje.tipopeticion
    json_data["entidadpeticion"] = mensaje.entidadpeticion

    # Convertir la propiedad "documento"
    json_data["documento"] = convertir_documento_a_json(mensaje.documento)

    return json_data

def convertir_documento_a_json(documento):
    """Convierte un objeto Documento a JSON."""

    json_data = {}

    # Convertir la propiedad "cabecera_documento"
    json_data["cabecera_documento"] = [convertir_parametro_a_json(parametro) for parametro in documento.cabecera_documento]

    # Convertir la propiedad "lineas_documento"
    json_data["lineas_documento"] = [[convertir_parametro_a_json(parametro) for parametro in linea]for linea in documento.lineas_documento]
    return json_data

def convertir_parametro_a_json(parametro):
    """Convierte un objeto Parametro a JSON."""
    is_float = isinstance(parametro.valor, float) # PARA REMPLAZAR EL PUNTO DEL FLOAT POR UNA COMILLA
    return {"campo": parametro.campo, "valor": str(parametro.valor).replace(".",",") if is_float else str(parametro.valor).replace('"','\"').replace('″','\"'), "tipo": parametro.tipo}

def json_list_to_json_dump(value):
    """Formatea la lista Json a tipo Texto tipo JSON.
    Args:
        value (List): Lista de valores tipo Json.
    Returns:
        Text: Texto en formateado
    """
    return json.dumps(value, indent=4)

def convertir_fecha(valor):
    """Convierte un valor de tipo datetime o date a una cadena con formato "%d/%m/%Y".
        Args:
            valor: Valor de tipo datetime o date.
        Returns:
            Cadena con la fecha formateada.
        """

    if isinstance(valor, datetime):
        return valor.date().strftime("%d/%m/%Y")
    elif isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    else:
        return None
       
def cuadrar(s, length=8):
    """Añade espacios a una cadena hasta alcanzar una longitud especificada, gestionando cadenas vacías y valores no numéricos.
    Args:
        s: La cadena a la que se añadirán espacios.
        length: La longitud deseada de la cadena con espacios (por defecto 8).
    Return:
        La cadena con espacios añadidos.
    """    
    try:
        if s is not None and s.strip():
            s = s.strip()
            if s.isdigit():
                s = s.rjust(length, " ")
        elif s is None or not s.strip():
            s = ""
    except Exception as ex:
        raise ValidationError((f"No se puede cuadrar el COD {s}: {format(ex)}"))
    return s