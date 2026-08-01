# Copyright Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class TlPikoAttributeRule(models.Model):
    """Regla regex -> valor de atributo.

    Diseñada para características técnicas (escala, época, administración,
    interfaz digital...), NO para generar variantes: los atributos creados por
    las reglas se fuerzan a `no_variant`, porque en estas tiendas cada
    combinación ya es un artículo con su propia referencia.
    """

    _name = "tl.piko.attribute.rule"
    _description = "Regla de extracción de características"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    source_id = fields.Many2one(
        "tl.piko.source",
        ondelete="cascade",
        help="Vacío = la regla se aplica a todas las fuentes.",
    )
    attribute_id = fields.Many2one(
        "product.attribute", required=True, ondelete="cascade"
    )
    field_source = fields.Selection(
        [
            ("name", "Nombre"),
            ("default_code", "Referencia"),
            ("description", "Descripción"),
            ("url", "URL"),
            ("categ_path", "Ruta de categoría"),
            ("spec", "Fila de la tabla de características"),
            ("all", "Todo el texto"),
        ],
        default="name",
        required=True,
    )
    spec_label = fields.Char(
        "Etiqueta de la fila",
        help="Etiqueta tal cual aparece en la ficha, p.ej. 'Type of current'. "
             "No distingue mayúsculas ni los dos puntos finales.",
    )
    regex = fields.Char(
        help="Expresión regular Python. Se evalúa sin distinguir mayúsculas "
             "salvo que actives 'Sensible a mayúsculas'. Con el modo 'Valor de "
             "la fila' no se usa.",
    )
    case_sensitive = fields.Boolean(default=False)
    value_mode = fields.Selection(
        [
            ("fixed", "Valor fijo"),
            ("capture", "Grupo capturado"),
            ("value", "Valor de la fila"),
        ],
        default="fixed",
        required=True,
    )
    value_name = fields.Char(
        "Valor", help="Nombre del valor de atributo (modo 'Valor fijo')."
    )
    capture_group = fields.Integer(default=1)
    value_mapping = fields.Text(
        "Normalización",
        help="Una línea por equivalencia: capturado = Valor final.\n"
             "Ej.:\nDB AG = DB AG\nOEBB = ÖBB",
    )
    match_position = fields.Selection(
        [("first", "Primera coincidencia"), ("last", "Última coincidencia")],
        default="first",
        required=True,
        help="Útil cuando el dato está al final del nombre (p.ej. la época, "
             "para no confundirla con la serie 'V 60' o 'V 200').",
    )
    multi = fields.Boolean(
        "Múltiples coincidencias",
        help="Recoge todas las coincidencias, no solo la primera "
             "(p.ej. varias interfaces digitales).",
    )
    stop_after_match = fields.Boolean(
        "Detener el atributo al acertar",
        default=True,
        help="Si acierta, no se evalúan más reglas del mismo atributo.",
    )

    @api.constrains("regex", "value_mode", "spec_label")
    def _check_regex(self):
        for rule in self:
            if rule.value_mode == "value":
                if not rule.spec_label:
                    raise ValidationError(
                        _("La regla '%s' necesita una etiqueta de fila.", rule.name)
                    )
                continue
            if not rule.regex:
                raise ValidationError(
                    _("La regla '%s' necesita una expresión regular.", rule.name)
                )
            try:
                re.compile(rule.regex)
            except re.error as exc:
                raise ValidationError(
                    _("Expresión regular inválida en '%(rule)s': %(err)s",
                      rule=rule.name, err=exc)
                ) from exc

    @api.constrains("value_mode", "value_name")
    def _check_value(self):
        for rule in self:
            if rule.value_mode == "fixed" and not rule.value_name:
                raise ValidationError(
                    _("La regla '%s' necesita un valor fijo.", rule.name)
                )

    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        rules._force_no_variant()
        return rules

    def _force_no_variant(self):
        attributes = self.attribute_id.filtered(
            lambda a: a.create_variant != "no_variant"
        )
        if attributes:
            _logger.info(
                "Forzando create_variant=no_variant en: %s", attributes.mapped("name")
            )
            attributes.create_variant = "no_variant"

    # ------------------------------------------------------------------
    def _get_text(self, line):
        self.ensure_one()
        if self.field_source == "spec":
            return line._spec_value(self.spec_label)
        if self.field_source == "all":
            parts = [line.name, line.default_code, line.description, line.categ_path]
            return " ".join(p for p in parts if p)
        return getattr(line, self.field_source, False) or ""

    def _normalize(self, raw):
        self.ensure_one()
        raw = (raw or "").strip()
        for row in (self.value_mapping or "").splitlines():
            if "=" not in row:
                continue
            key, value = row.split("=", 1)
            if key.strip().lower() == raw.lower():
                return value.strip()
        return raw

    def _match(self, line):
        """Devuelve la lista de nombres de valor detectados por esta regla."""
        self.ensure_one()
        text = self._get_text(line)
        if not text:
            return []
        if self.value_mode == "value":
            value = self._normalize(text)
            return [value] if value else []
        flags = 0 if self.case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(self.regex, flags)
        except re.error:
            return []
        if self.value_mode == "fixed":
            return [self.value_name] if pattern.search(text) else []
        results = []
        matches = list(pattern.finditer(text))
        if not self.multi and self.match_position == "last":
            matches = matches[-1:]
        for match in matches:
            try:
                raw = match.group(self.capture_group or 1)
            except IndexError:
                continue
            value = self._normalize(raw)
            if value and value not in results:
                results.append(value)
            if not self.multi:
                break
        return results

    # ------------------------------------------------------------------
    @api.model
    def apply_to_line(self, line):
        """Aplica las reglas de la fuente y devuelve un recordset de valores."""
        rules = self.search(
            ["|", ("source_id", "=", False), ("source_id", "=", line.source_id.id)]
        )
        values = self.env["product.attribute.value"]
        done_attributes = self.env["product.attribute"]
        for rule in rules:
            if rule.stop_after_match and rule.attribute_id in done_attributes:
                continue
            names = rule._match(line)
            if not names:
                continue
            for name in names:
                values |= rule.attribute_id._tl_piko_get_value(name)
            done_attributes |= rule.attribute_id
        return values


class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    def _tl_piko_get_value(self, name):
        """Devuelve (creando si hace falta) el valor con ese nombre."""
        self.ensure_one()
        name = (name or "").strip()
        if not name:
            return self.env["product.attribute.value"]
        value = self.value_ids.filtered(lambda v: v.name.lower() == name.lower())[:1]
        if value:
            return value
        return self.env["product.attribute.value"].create(
            {"name": name, "attribute_id": self.id}
        )
