# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Parser puro (sin ORM) del fichero de enlace de entrada SUENLACE.DAT.

Reglas generales del formato a3asesor Eco/Con
---------------------------------------------
* Organización SECUENCIAL, longitud fija de 512 bytes por registro.
* Cada registro termina en CR+LF (ASCII 13 + ASCII 10) en las posiciones
  511-512.
* El discriminador del tipo de registro está SIEMPRE en la posición 15.
* Las posiciones documentadas son 1-based e inclusivas: "16 a 27" =>
  slice python [15:27].
* Importes: signo + 10 enteros + '.' + 2 decimales -> '+0000001000.00'.
* Porcentajes: 'xx.xx'.

Este módulo se limita a extraer la información a diccionarios tipados; la
lógica de negocio vive en `suenlace_import.py`.
"""
import logging
from datetime import date

_logger = logging.getLogger(__name__)

RECORD_LENGTH = 512
MIN_LINE_LENGTH = 15


class SuenlaceFieldError(Exception):
    """Error al interpretar un campo concreto de un registro."""


def _slice(line, start_1based, length):
    start = start_1based - 1
    return line[start:start + length]


def parse_str(line, start, length):
    return _slice(line, start, length).rstrip()


def parse_raw(line, start, length):
    return _slice(line, start, length)


def parse_amount(line, start, length=14):
    raw = _slice(line, start, length).strip()
    if not raw:
        return 0.0
    sign = 1.0
    if raw[0] in "+-":
        sign = -1.0 if raw[0] == "-" else 1.0
        raw = raw[1:]
    raw = raw.strip()
    if not raw:
        return 0.0
    try:
        return sign * float(raw)
    except ValueError:
        cleaned = raw.replace(" ", "")
        try:
            return sign * float(cleaned)
        except ValueError as exc:
            raise SuenlaceFieldError(
                "Importe no numérico en posición %(pos)s: %(raw)r"
                % {"pos": start, "raw": raw}
            ) from exc


def parse_percent(line, start, length=5):
    raw = _slice(line, start, length).strip()
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        cleaned = raw.replace(" ", "")
        return float(cleaned) if cleaned else 0.0


def parse_date(line, start, length=8):
    raw = _slice(line, start, length).strip()
    if not raw or raw == "0" * length or not raw.isdigit():
        return None
    try:
        return date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError:
        _logger.warning("Fecha inválida en posición %(pos)s: %(raw)r",
                        {"pos": start, "raw": raw})
        return None


def record_type(line):
    """Identificador lógico del tipo de registro (considera subtipos 69/73)."""
    rtype = _slice(line, 15, 1)
    if rtype == "V":
        return "VA" if _slice(line, 69, 1) == "A" else "V"
    if rtype == "C":
        amp = _slice(line, 73, 1)
        if amp == "B":
            return "CB"
        if amp == "R":
            return "CR"
        if amp == "F":
            return "CF"
        return "C"
    return rtype


def _common_header(line, rtype):
    return {
        "_type": rtype,
        "formato": _slice(line, 1, 1),
        "empresa": parse_str(line, 2, 5),
        "fecha": parse_date(line, 7, 8),
        "moneda": _slice(line, 509, 1) or "E",
    }


def parse_type_0(line):
    """Alta de apuntes sin IVA."""
    d = _common_header(line, "0")
    d.update({
        "cuenta": parse_raw(line, 16, 12).strip(),
        "cuenta_desc": parse_str(line, 28, 30),
        "tipo_importe": _slice(line, 58, 1),
        "referencia": parse_str(line, 59, 10),
        "linea": _slice(line, 69, 1),
        "apunte_desc": parse_str(line, 70, 30),
        "importe": parse_amount(line, 100, 14),
        "asiento_nomina": _slice(line, 251, 1) == "S",
        "tiene_analitica": _slice(line, 252, 1) == "S",
    })
    return d


def parse_type_1_2(line, rtype):
    """Cabecera de factura con IVA (1=facturas, 2=rectificativas/abonos)."""
    d = _common_header(line, rtype)
    d.update({
        "cuenta": parse_raw(line, 16, 12).strip(),
        "cuenta_desc": parse_str(line, 28, 30),
        "tipo_factura": _slice(line, 58, 1),
        "num_factura": parse_str(line, 59, 10),
        "linea": _slice(line, 69, 1),
        "apunte_desc": parse_str(line, 70, 30),
        "importe": parse_amount(line, 100, 14),
        "nif": parse_str(line, 176, 14),
        "nombre": parse_str(line, 190, 40),
        "cp": parse_str(line, 230, 5),
        "fecha_operacion": parse_date(line, 237, 8),
        "fecha_factura": parse_date(line, 245, 8),
        "num_factura_sii": parse_str(line, 253, 60),
        "pais": parse_str(line, 374, 2),
        "tipo_documento": parse_str(line, 376, 2),
    })
    return d


def parse_type_9(line):
    """Detalle de IVA de la factura."""
    d = _common_header(line, "9")
    d.update({
        "cuenta": parse_raw(line, 16, 12).strip(),
        "cuenta_desc": parse_str(line, 28, 30),
        "tipo_importe": _slice(line, 58, 1),
        "num_factura": parse_str(line, 59, 10),
        "linea": _slice(line, 69, 1),
        "apunte_desc": parse_str(line, 70, 30),
        "subtipo_factura": parse_str(line, 100, 2),
        "base": parse_amount(line, 102, 14),
        "pct_iva": parse_percent(line, 116, 5),
        "cuota_iva": parse_amount(line, 121, 14),
        "pct_recargo": parse_percent(line, 135, 5),
        "cuota_recargo": parse_amount(line, 140, 14),
        "pct_retencion": parse_percent(line, 154, 5),
        "cuota_retencion": parse_amount(line, 159, 14),
        "impreso": parse_str(line, 173, 2),
        "sujeta_iva": _slice(line, 175, 1),
        "marca_415": _slice(line, 176, 1),
        "criterio_caja": _slice(line, 177, 1) == "S",
        "iva_0_recargo": _slice(line, 178, 1),
        "cuenta_iva_soportado": parse_raw(line, 192, 12).strip(),
        "cuenta_recargo_soportado": parse_raw(line, 204, 12).strip(),
        "cuenta_retencion": parse_raw(line, 216, 12).strip(),
        "cuenta_iva2_repercutido": parse_raw(line, 228, 12).strip(),
        "cuenta_recargo2_repercutido": parse_raw(line, 240, 12).strip(),
        "tiene_analitica": _slice(line, 252, 1) == "S",
    })
    return d


def parse_type_3(line):
    """Comentario asociado al apunte."""
    d = _common_header(line, "3")
    d["observaciones"] = parse_str(line, 59, 195)
    return d


def parse_type_4(line):
    """Datos de ampliación de factura (SII / modelo 340)."""
    d = _common_header(line, "4")
    d.update({
        "fecha_factura_rectificar": parse_date(line, 59, 8),
        "num_factura_rectificar": parse_str(line, 67, 60),
        "num_dua": parse_str(line, 127, 18),
        "cuenta_proveedor": parse_raw(line, 145, 12).strip(),
        "tipo_factura_sii": _slice(line, 157, 1),
        "clave_factura_sii": _slice(line, 158, 1),
        "nif_representante": parse_str(line, 159, 14),
        "num_factura_inicial": parse_str(line, 173, 40),
        "num_factura_final": parse_str(line, 213, 40),
        "num_documentos": parse_str(line, 253, 18),
        "factura_terceros": _slice(line, 271, 1) == "S",
        "varios_destinatarios": _slice(line, 272, 1) == "S",
        "cupones_desc": _slice(line, 273, 1) == "S",
        "marca_total_metalico": _slice(line, 274, 1) == "S",
        "importe_metalico": parse_amount(line, 275, 14),
        "marca_transmision_bienes": _slice(line, 289, 1) == "S",
        "importe_transmision_bienes": parse_amount(line, 290, 14),
        "tipo_factura_eri": _slice(line, 304, 1),
        "identificacion_factura": parse_str(line, 305, 49),
        "tipo_exencion": _slice(line, 354, 1),
        "tipo_no_sujecion": _slice(line, 355, 1),
    })
    return d


def parse_type_5(line):
    """Descripción de la factura (SII)."""
    d = _common_header(line, "5")
    d["descripcion_factura"] = parse_str(line, 59, 451)
    return d


def parse_type_6(line):
    """Identificador único de factura."""
    d = _common_header(line, "6")
    d.update({
        "id_factura": parse_str(line, 59, 36),
        "aplicacion_origen": parse_str(line, 95, 3),
    })
    return d


def parse_type_n(line):
    """Alta registro modelo 190 (perceptor / retenciones)."""
    d = _common_header(line, "N")
    d.update({
        "nif_perceptor": parse_str(line, 59, 14),
        "nombre": parse_str(line, 73, 30),
        "clave_190": _slice(line, 104, 1) or "A",
        "tipo_relacion_subclave": parse_str(line, 105, 2),
        "importe_percepcion": parse_amount(line, 107, 14),
        "importe_retenciones": parse_amount(line, 121, 14),
        "importe_valoracion": parse_amount(line, 135, 14),
        "ingresos_cuenta_efectuados": parse_amount(line, 149, 14),
        "ingresos_cuenta_repercutidos": parse_amount(line, 163, 14),
        "importe_reducciones": parse_amount(line, 177, 14),
        "importe_seg_social": parse_amount(line, 191, 14),
    })
    return d


def parse_type_v(line):
    """Alta de vencimiento (o identificación factura si indicador='I')."""
    indicador = _slice(line, 69, 1)
    d = _common_header(line, "V")
    d.update({
        "fecha_vencimiento": parse_date(line, 7, 8),
        "cuenta": parse_raw(line, 16, 12).strip(),
        "cuenta_desc": parse_str(line, 28, 30),
        "tipo_vencimiento": _slice(line, 58, 1),
        "num_factura": parse_str(line, 59, 10),
        "indicador": indicador,
    })
    if indicador == "I":
        d.update({
            "subtipo": "identificacion",
            "tipo_factura_eri": _slice(line, 70, 1),
            "identificacion_factura": parse_str(line, 71, 49),
            "base_1": parse_amount(line, 120, 14),
            "cuota_1": parse_amount(line, 134, 14),
            "recargo_1": parse_amount(line, 148, 14),
            "base_2": parse_amount(line, 162, 14),
            "cuota_2": parse_amount(line, 176, 14),
            "recargo_2": parse_amount(line, 190, 14),
            "base_3": parse_amount(line, 204, 14),
            "cuota_3": parse_amount(line, 218, 14),
            "recargo_3": parse_amount(line, 232, 14),
        })
    else:
        d.update({
            "subtipo": "vencimiento",
            "vencimiento_desc": parse_str(line, 70, 30),
            "importe": parse_amount(line, 100, 14),
            "fecha_factura": parse_date(line, 114, 8),
            "cuenta_tesoreria": parse_raw(line, 122, 12).strip(),
            "forma_pago": parse_str(line, 134, 2),
            "num_vencimiento": parse_str(line, 136, 2),
        })
    return d


def parse_type_va(line):
    """Ampliación de la alta de vencimientos (posición 69 = 'A')."""
    d = _common_header(line, "VA")
    d.update({
        "fecha_vencimiento": parse_date(line, 7, 8),
        "tipo_cobro_pago": parse_str(line, 59, 2),
        "fecha_cobro_pago": parse_date(line, 61, 8),
        "estado": _slice(line, 70, 1),
        "num_efecto": parse_str(line, 71, 15),
        "ccc": parse_str(line, 94, 20),
        "nombre_oficina": parse_str(line, 114, 20),
        "domicilio_oficina": parse_str(line, 134, 25),
        "codigo_nota": parse_str(line, 159, 2),
        "titulo_nota": parse_str(line, 161, 40),
    })
    return d


def parse_type_b(line):
    """Baja de vencimientos."""
    d = _common_header(line, "B")
    d.update({
        "fecha_vencimiento": parse_date(line, 7, 8),
        "cuenta": parse_raw(line, 16, 12).strip(),
        "tipo_vencimiento": _slice(line, 58, 1),
        "num_factura": parse_str(line, 59, 10),
        "vencimiento_desc": parse_str(line, 70, 30),
        "importe": parse_amount(line, 100, 14),
        "fecha_factura": parse_date(line, 114, 8),
        "cuenta_tesoreria": parse_raw(line, 122, 12).strip(),
        "forma_pago": parse_str(line, 134, 2),
        "num_vencimiento": parse_str(line, 136, 2),
    })
    return d


def parse_type_c(line):
    """Alta / modificación de cuentas y/o clientes y proveedores."""
    d = _common_header(line, "C")
    d.update({
        "fecha_alta": parse_date(line, 7, 8),
        "cuenta": parse_raw(line, 16, 12).strip(),
        "cuenta_desc": parse_str(line, 28, 30),
        "actualizar_saldo": _slice(line, 58, 1) == "S",
        "saldo_inicial": parse_amount(line, 59, 14),
        "nif": parse_str(line, 78, 14),
        "siglas_via": parse_str(line, 92, 2),
        "via_publica": parse_str(line, 94, 30),
        "numero": parse_str(line, 124, 5),
        "escalera": parse_str(line, 129, 2),
        "piso": parse_str(line, 131, 2),
        "puerta": parse_str(line, 133, 2),
        "municipio": parse_str(line, 135, 20),
        "cp": parse_str(line, 155, 5),
        "provincia": parse_str(line, 160, 15),
        "pais": parse_str(line, 175, 3),
        "telefono": parse_str(line, 178, 12),
        "extension": parse_str(line, 190, 4),
        "fax": parse_str(line, 194, 12),
        "email": parse_str(line, 206, 30),
        "criterio_caja": _slice(line, 238, 1) == "S",
        "cuenta_contrapartida": parse_raw(line, 241, 12).strip(),
        "tipo_documento": parse_str(line, 255, 2),
    })
    return d


def parse_type_cb(line):
    """C con Ampliación = B : CCC bancarias del cliente / proveedor."""
    d = _common_header(line, "CB")
    d.update({
        "nif": parse_str(line, 74, 14),
        "nombre": parse_str(line, 88, 30),
        "ccc": parse_str(line, 118, 20),
        "nombre_oficina": parse_str(line, 138, 20),
        "domicilio_oficina": parse_str(line, 158, 25),
        "cuenta_omision": _slice(line, 183, 1) == "S",
    })
    return d


def parse_type_cr(line):
    """C con Ampliación = R : datos de ampliación del modelo 190."""
    d = _common_header(line, "CR")
    d.update({
        "nif": parse_str(line, 74, 14),
        "anio_nacimiento": parse_str(line, 88, 4),
        "nif_conyuge": parse_str(line, 92, 14),
        "situacion_laboral": _slice(line, 106, 1),
        "indicador_discapacidad": _slice(line, 107, 1),
        "prolongacion_actividad": _slice(line, 108, 1),
        "movilidad_geografica": _slice(line, 109, 1),
        "nif_representante": parse_str(line, 110, 14),
        "hijos_menores_3": parse_str(line, 124, 2),
        "hijos_menores_3_entero": parse_str(line, 126, 2),
        "hijos_mayores_3": parse_str(line, 128, 2),
        "hijos_mayores_3_entero": parse_str(line, 130, 2),
    })
    return d


def parse_type_cf(line):
    """C con Ampliación = F : nombre fiscal."""
    d = _common_header(line, "CF")
    d.update({
        "nif": parse_str(line, 74, 14),
        "nombre_fiscal": parse_str(line, 88, 30),
    })
    return d


def parse_type_a(line):
    """Tabla de niveles de la distribución analítica."""
    d = _common_header(line, "A")
    d.update({
        "num_niveles": _slice(line, 59, 1),
        "nombre_centro": parse_str(line, 60, 10),
        "long_centro": _slice(line, 70, 1),
        "nombre_departamento": parse_str(line, 71, 10),
        "long_departamento": _slice(line, 81, 1),
        "nombre_division": parse_str(line, 82, 10),
        "long_division": _slice(line, 92, 1),
        "nombre_seccion": parse_str(line, 93, 10),
        "long_seccion": _slice(line, 103, 1),
    })
    return d


def parse_type_d(line):
    """Distribución analítica del apunte."""
    d = _common_header(line, "D")
    d.update({
        "cuenta": parse_raw(line, 16, 12).strip(),
        "cuenta_desc": parse_str(line, 28, 30),
        "importe_total": parse_amount(line, 59, 14),
        "num_linea_apunte": parse_str(line, 73, 3),
        "linea_distribucion": _slice(line, 76, 1),
        "codigo_centro": parse_str(line, 77, 4),
        "codigo_departamento": parse_str(line, 81, 4),
        "codigo_division": parse_str(line, 85, 4),
        "codigo_seccion": parse_str(line, 89, 4),
        "desc_centro": parse_str(line, 93, 30),
        "desc_departamento": parse_str(line, 123, 30),
        "desc_division": parse_str(line, 153, 30),
        "desc_seccion": parse_str(line, 183, 30),
        "importe_distribucion": parse_amount(line, 213, 14),
        "porcentaje_distribucion": parse_percent(line, 227, 6),
    })
    return d


_DISPATCH = {
    "0": parse_type_0,
    "1": lambda line: parse_type_1_2(line, "1"),
    "2": lambda line: parse_type_1_2(line, "2"),
    "3": parse_type_3,
    "4": parse_type_4,
    "5": parse_type_5,
    "6": parse_type_6,
    "9": parse_type_9,
    "N": parse_type_n,
    "V": parse_type_v,
    "VA": parse_type_va,
    "B": parse_type_b,
    "C": parse_type_c,
    "CB": parse_type_cb,
    "CR": parse_type_cr,
    "CF": parse_type_cf,
    "A": parse_type_a,
    "D": parse_type_d,
}


def parse_line(line):
    """Parsea una línea del fichero y devuelve un dict (o marca no soportado)."""
    if len(line) < MIN_LINE_LENGTH:
        return None
    rtype = record_type(line)
    func = _DISPATCH.get(rtype)
    if func is None:
        _logger.warning("Tipo de registro no soportado: %r", rtype)
        return {"_type": rtype, "_unsupported": True, "_raw": line}
    return func(line)


def detect_encoding(raw_bytes):
    """Detecta el encoding del fichero. a3 suele generar CP1252/Latin-1."""
    try:
        import chardet
        guess = chardet.detect(raw_bytes)
        enc = (guess or {}).get("encoding")
        if enc:
            return enc
    except Exception:  # pragma: no cover
        _logger.debug("chardet no disponible, se asume cp1252")
    return "cp1252"


def iter_records(raw_bytes, encoding=None):
    """Itera sobre los registros y devuelve tuplas (numero, dict_parseado)."""
    if encoding is None:
        encoding = detect_encoding(raw_bytes)
    try:
        text = raw_bytes.decode(encoding, errors="replace")
    except LookupError:
        text = raw_bytes.decode("cp1252", errors="replace")

    if "\n" in text or "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [ln for ln in text.split("\n") if ln.strip()]
    else:
        lines = [text[i:i + RECORD_LENGTH]
                 for i in range(0, len(text), RECORD_LENGTH)]
        lines = [ln for ln in lines if ln.strip()]

    for idx, line in enumerate(lines, start=1):
        parsed = parse_line(line)
        if parsed is not None:
            yield idx, parsed
