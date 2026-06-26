import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .bc3_parser import BC3Parser, BC3ParseError


class Bc3File(models.Model):
    _name = "bc3.file"
    _description = "BC3 File"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, tracking=True)
    data_file = fields.Binary(string="BC3 File", attachment=True)
    filename = fields.Char()
    state = fields.Selection(
        [("draft", "Draft"), ("parsed", "Parsed"), ("error", "Error")],
        default="draft",
        required=True,
        tracking=True,
    )
    error_message = fields.Text(readonly=True)
    warning_message = fields.Text(readonly=True)
    property_file = fields.Char(readonly=True)
    version = fields.Char(readonly=True)
    program = fields.Char(readonly=True)
    charset = fields.Char(readonly=True)
    encoding = fields.Char(readonly=True)
    comment = fields.Char(readonly=True)
    info_type = fields.Selection(
        [("1", "Database"), ("2", "Budget"), ("3", "Certification"), ("4", "Database update"), ("", "Unknown")],
        string="Information Type",
        readonly=True,
    )
    certification_number = fields.Char(readonly=True)
    certification_date = fields.Date(readonly=True)
    url_base = fields.Char(readonly=True)
    raw_k = fields.Text(string="Raw ~K", readonly=True)
    record_count = fields.Integer(readonly=True)
    concept_count = fields.Integer(readonly=True)
    decomposition_count = fields.Integer(readonly=True)
    measurement_count = fields.Integer(readonly=True)
    raw_record_ids = fields.One2many("bc3.raw.record", "file_id", string="Raw Records")
    concept_ids = fields.One2many("bc3.concept", "file_id", string="Concepts")
    decomposition_line_ids = fields.One2many("bc3.decomposition.line", "file_id", string="Decompositions")
    measurement_line_ids = fields.One2many("bc3.measurement.line", "file_id", string="Measurements")
    media_ref_ids = fields.One2many("bc3.concept.media", "file_id", string="Media References")

    def action_parse(self):
        for rec in self:
            rec._parse_file()
        return True

    def _parse_file(self):
        self.ensure_one()
        if not self.data_file:
            raise UserError(_("Please upload a BC3 file first."))
        self.raw_record_ids.unlink()
        self.concept_ids.unlink()
        self.decomposition_line_ids.unlink()
        self.measurement_line_ids.unlink()
        payload = base64.b64decode(self.data_file)
        try:
            parsed = BC3Parser().parse(payload, self.filename or self.name)
        except BC3ParseError as exc:
            self.write({"state": "error", "error_message": str(exc)})
            raise UserError(str(exc)) from exc
        concept_by_code = {}
        raw_vals = [
            {
                "file_id": self.id,
                "sequence": item.sequence,
                "record_type": item.record_type,
                "raw_text": item.raw,
            }
            for item in parsed.records
        ]
        if raw_vals:
            self.env["bc3.raw.record"].create(raw_vals)
        for concept in {id(c): c for c in parsed.concepts.values()}.values():
            code = concept.code
            concept_rec = self.env["bc3.concept"].create({
                "file_id": self.id,
                "code": code,
                "normalized_code": self.env["bc3.concept"]._normalize_code(code),
                "name": concept.summary or code,
                "unit_name": concept.unit,
                "concept_type": concept.concept_type,
                "category": self.env["bc3.concept"]._get_category_from_code(code, concept.concept_type),
                "price_unit": concept.prices[0] if concept.prices else 0.0,
                "price_date_raw": concept.price_dates[0] if concept.price_dates else "",
                "text": concept.text,
                "technical_json": str(concept.technical or {}),
            })
            media_vals = []
            for seq, media in enumerate(concept.media_refs or [], start=1):
                media_vals.append({
                    "concept_id": concept_rec.id,
                    "sequence": seq,
                    "source": media.source if media.source in ("G", "F") else "G",
                    "filename": media.filename,
                    "type_code": media.type_code,
                    "description": media.description,
                    "url_ext": media.url_ext,
                    "is_image": media.is_image,
                })
            if media_vals:
                self.env["bc3.concept.media"].create(media_vals)
            concept_by_code[code] = concept_rec
            for alias in concept.aliases:
                self.env["bc3.concept.code"].create({
                    "concept_id": concept_rec.id,
                    "name": alias,
                    "normalized_code": self.env["bc3.concept"]._normalize_code(alias),
                })
        decomp_vals = []
        for line in parsed.decomposition_lines:
            parent = concept_by_code.get(line.parent_code)
            child = concept_by_code.get(line.child_code)
            decomp_vals.append({
                "file_id": self.id,
                "parent_code": line.parent_code,
                "child_code": line.child_code,
                "parent_concept_id": parent.id if parent else False,
                "child_concept_id": child.id if child else False,
                "sequence": line.sequence,
                "factor": line.factor,
                "performance": line.performance,
                "percent_codes": line.percent_codes,
            })
        if decomp_vals:
            self.env["bc3.decomposition.line"].create(decomp_vals)
        measurement_vals = []
        for measurement in parsed.measurements:
            parent = concept_by_code.get(measurement.parent_code)
            child = concept_by_code.get(measurement.child_code)
            if measurement.items:
                for idx, item in enumerate(measurement.items, start=1):
                    measurement_vals.append(self._measurement_vals(measurement, item, idx, parent, child))
            else:
                measurement_vals.append(self._measurement_vals(measurement, None, 1, parent, child))
        if measurement_vals:
            self.env["bc3.measurement.line"].create(measurement_vals)
        self.write({
            "state": "parsed",
            "error_message": False,
            "warning_message": "\n".join(parsed.warnings),
            "property_file": parsed.property_file,
            "version": parsed.version,
            "program": parsed.program,
            "charset": parsed.charset,
            "encoding": parsed.encoding,
            "comment": parsed.comment,
            "info_type": parsed.info_type if parsed.info_type in ("1", "2", "3", "4") else "",
            "certification_number": parsed.certification_number,
            "certification_date": parsed.certification_date,
            "url_base": parsed.url_base,
            "raw_k": parsed.raw_k,
            "record_count": len(parsed.records),
            "concept_count": len(concept_by_code),
            "decomposition_count": len(parsed.decomposition_lines),
            "measurement_count": len(measurement_vals),
        })

    def _measurement_vals(self, measurement, item, idx, parent, child):
        vals = {
            "file_id": self.id,
            "parent_code": measurement.parent_code,
            "child_code": measurement.child_code,
            "parent_concept_id": parent.id if parent else False,
            "child_concept_id": child.id if child else False,
            "position_path": measurement.position_path,
            "measurement_total": measurement.measurement_total,
            "sequence": idx,
            "label": measurement.label,
        }
        if item:
            vals.update({
                "line_type": item.line_type,
                "comment": item.comment,
                "bim_id": item.bim_id,
                "units": item.units,
                "length": item.length,
                "width": item.width,
                "height": item.height,
                "subtotal": item.subtotal,
            })
        return vals


class Bc3RawRecord(models.Model):
    _name = "bc3.raw.record"
    _description = "BC3 Raw Record"
    _order = "file_id, sequence"

    file_id = fields.Many2one("bc3.file", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(required=True)
    record_type = fields.Char(required=True, index=True)
    raw_text = fields.Text(required=True)
