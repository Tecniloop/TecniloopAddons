import re

from odoo import api, fields, models


PURE_NUMBER_RE = re.compile(r"^[+-]?[0-9]+(?:[.,][0-9]+)?$")
UNIT_PATTERNS = (
    (re.compile(r"\s+\(RPM\)$", re.IGNORECASE), "RPM"),
    (re.compile(r"\s+mm$", re.IGNORECASE), "mm"),
    (re.compile(r"\s+cm$", re.IGNORECASE), "cm"),
    (re.compile(r"\s+kg$", re.IGNORECASE), "kg"),
    (re.compile(r"\s+g$", re.IGNORECASE), "g"),
)


class ProductNextmartSpecification(models.Model):
    _name = "product.nextmart.specification"
    _description = "Nextmart Product Technical Specification"
    _order = "sequence, id"

    product_tmpl_id = fields.Many2one(
        comodel_name="product.template",
        string="Product Template",
        required=True,
        index=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product Variant",
        index=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    value = fields.Char()
    normalized_name = fields.Char(index=True)
    numeric_value = fields.Float()
    unit = fields.Char()

    @api.model
    def _prepare_values(self, product_tmpl, product, item):
        original_name = (item.get("name") or "").strip()
        value = (item.get("value") or "").strip()
        clean_name = original_name
        unit = False

        for pattern, detected_unit in UNIT_PATTERNS:
            if pattern.search(clean_name):
                clean_name = pattern.sub("", clean_name).strip()
                unit = detected_unit
                break

        if "°" in clean_name:
            unit = "°"

        numeric_value = 0.0
        if PURE_NUMBER_RE.match(value):
            numeric_value = float(value.replace(",", "."))

        return {
            "product_tmpl_id": product_tmpl.id,
            "product_id": product.id if product else False,
            "sequence": item.get("sequence", 10),
            "name": original_name,
            "normalized_name": clean_name,
            "value": value,
            "numeric_value": numeric_value,
            "unit": unit,
        }
