from odoo import api, fields, models


class Bc3Concept(models.Model):
    _name = "bc3.concept"
    _description = "BC3 Concept"
    _order = "file_id, code"
    _rec_name = "display_name"

    file_id = fields.Many2one("bc3.file", required=True, ondelete="cascade", index=True)
    code = fields.Char(required=True, index=True)
    normalized_code = fields.Char(index=True)
    display_name = fields.Char(compute="_compute_display_name", store=True)
    name = fields.Char(required=True)
    unit_name = fields.Char(string="BC3 Unit")
    uom_id = fields.Many2one("uom.uom", string="Odoo UoM")
    concept_type = fields.Char(string="BC3 Type")
    category = fields.Selection(
        [
            ("root", "Root"),
            ("chapter", "Chapter"),
            ("work_unit", "Work Unit"),
            ("resource", "Resource"),
            ("percentage", "Percentage"),
            ("other", "Other"),
        ],
        required=True,
        default="other",
        index=True,
    )
    price_unit = fields.Float(digits="Product Price")
    price_date_raw = fields.Char()
    text = fields.Text()
    technical_json = fields.Text()
    alias_ids = fields.One2many("bc3.concept.code", "concept_id", string="Aliases")
    media_ref_ids = fields.One2many("bc3.concept.media", "concept_id", string="Media References")
    media_ref_count = fields.Integer(compute="_compute_media_ref_count")

    _sql_constraints = [
        ("file_code_uniq", "unique(file_id, code)", "The BC3 concept code must be unique per file."),
    ]

    @api.depends("code", "name")
    def _compute_display_name(self):
        for concept in self:
            concept.display_name = "[%s] %s" % (concept.code or "", concept.name or "")

    @api.depends("media_ref_ids")
    def _compute_media_ref_count(self):
        for concept in self:
            concept.media_ref_count = len(concept.media_ref_ids)

    @api.model
    def _normalize_code(self, code):
        code = (code or "").strip()
        if code.endswith("##"):
            return code[:-2]
        if code.endswith("#"):
            return code[:-1]
        return code

    @api.model
    def _get_category_from_code(self, code, concept_type=False):
        code = (code or "").strip()
        if code.endswith("##"):
            return "root"
        if code.endswith("#"):
            return "chapter"
        if "%" in code or "&" in code or concept_type == "%":
            return "percentage"
        if concept_type in ("1", "2", "3", "4", "5"):
            return "resource"
        return "work_unit"


class Bc3ConceptCode(models.Model):
    _name = "bc3.concept.code"
    _description = "BC3 Concept Alias"
    _order = "concept_id, name"

    concept_id = fields.Many2one("bc3.concept", required=True, ondelete="cascade", index=True)
    file_id = fields.Many2one(related="concept_id.file_id", store=True, index=True)
    name = fields.Char(required=True)
    normalized_code = fields.Char(index=True)


class Bc3ConceptMedia(models.Model):
    _name = "bc3.concept.media"
    _description = "BC3 Concept Media Reference"
    _order = "concept_id, sequence, id"

    concept_id = fields.Many2one("bc3.concept", required=True, ondelete="cascade", index=True)
    file_id = fields.Many2one(related="concept_id.file_id", store=True, index=True)
    sequence = fields.Integer(default=10)
    source = fields.Selection([("G", "Graphic"), ("F", "Associated file")], required=True, default="G")
    filename = fields.Char(required=True)
    type_code = fields.Char()
    description = fields.Char()
    url_ext = fields.Char()
    is_image = fields.Boolean(index=True)
