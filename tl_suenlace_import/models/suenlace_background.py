# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Procesamiento incremental y en segundo plano para SUENLACE.

El objetivo de este archivo es que las acciones web solo preparen el lote y
retornen inmediatamente. El trabajo pesado se divide en lotes pequeños que se
ejecutan mediante una acción planificada nativa de Odoo. Si está instalado el
addon opcional ``tl_suenlace_import_queue_job``, el mismo motor por lotes se
encola en OCA Queue Job sin duplicar lógica.
"""
import base64
import datetime
import io
import json
import logging
import math

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

from . import suenlace_parser as parser

_logger = logging.getLogger(__name__)

MASTER_RECORD_TYPES = ("C", "CB", "CR", "CF")
INVOICE_CHILD_TYPES = ("9", "3", "4", "5", "6", "V", "VA", "B", "A", "D")
DOCUMENT_START_TYPES = ("0", "1", "2")
DEFAULT_BATCH_SIZE = 25
DEFAULT_PARSE_BATCH_SIZE = 2000


def _bool_param(env, key, default=True):
    value = env["ir.config_parameter"].sudo().get_param(
        key, "True" if default else "False"
    )
    return str(value).lower() in {"1", "true", "yes", "on"}


def _int_param(env, key, default):
    value = env["ir.config_parameter"].sudo().get_param(key, str(default))
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


class SuenlaceImport(models.Model):
    _inherit = "tl.suenlace.import"

    background_mode = fields.Boolean(
        string="Procesar en segundo plano",
        default=lambda self: _bool_param(
            self.env, "tl_suenlace_import.background_mode", True
        ),
        help=(
            "Divide el parseo y la creación de documentos en lotes y los "
            "ejecuta fuera de la petición web. Es el modo recomendado para "
            "evitar el timeout HTTP en migraciones voluminosas."
        ),
    )
    batch_size = fields.Integer(
        string="Documentos por lote",
        default=lambda self: _int_param(
            self.env, "tl_suenlace_import.batch_size", DEFAULT_BATCH_SIZE
        ),
        help="Número máximo de asientos o facturas procesados en cada lote.",
    )
    parse_batch_size = fields.Integer(
        string="Registros por lote de parseo",
        default=lambda self: _int_param(
            self.env,
            "tl_suenlace_import.parse_batch_size",
            DEFAULT_PARSE_BATCH_SIZE,
        ),
        help="Número máximo de registros DAT parseados en cada lote.",
    )
    processing_phase = fields.Selection(
        [
            ("idle", "Sin proceso"),
            ("parse", "Parseando"),
            ("masters", "Cuentas y terceros"),
            ("documents", "Documentos contables"),
            ("finalize", "Finalizando"),
        ],
        string="Fase",
        default="idle",
        readonly=True,
        copy=False,
        tracking=True,
    )
    requested_operation = fields.Selection(
        [("parse", "Solo parsear"), ("process", "Parsear y procesar")],
        default="parse",
        readonly=True,
        copy=False,
    )
    parse_cursor = fields.Integer(readonly=True, copy=False)
    parse_byte_offset = fields.Integer(readonly=True, copy=False)
    master_cursor = fields.Integer(readonly=True, copy=False)
    parse_document_counter = fields.Integer(readonly=True, copy=False)
    parse_current_document_key = fields.Char(readonly=True, copy=False)
    parse_current_document_type = fields.Selection(
        [("invoice", "Factura"), ("entry", "Asiento")],
        readonly=True,
        copy=False,
    )
    total_record_count = fields.Integer(
        string="Registros totales", readonly=True, copy=False
    )
    processed_document_count = fields.Integer(
        string="Documentos procesados", readonly=True, copy=False
    )
    total_document_count = fields.Integer(
        string="Documentos totales", readonly=True, copy=False
    )
    failed_document_count = fields.Integer(
        string="Documentos con error", readonly=True, copy=False
    )
    failed_master_count = fields.Integer(
        string="Maestros con error", readonly=True, copy=False
    )
    type_count_json = fields.Text(readonly=True, copy=False)
    last_batch_date = fields.Datetime(
        string="Último lote", readonly=True, copy=False
    )
    progress_percent = fields.Float(
        string="Progreso", compute="_compute_progress_percent"
    )

    @api.depends(
        "state",
        "processing_phase",
        "parse_cursor",
        "total_record_count",
        "processed_document_count",
        "total_document_count",
    )
    def _compute_progress_percent(self):
        for record in self:
            if record.state == "done":
                record.progress_percent = 100.0
                continue
            if record.processing_phase == "parse":
                total = record.total_record_count or 1
                record.progress_percent = min(
                    30.0, 30.0 * record.parse_cursor / total
                )
            elif record.processing_phase == "masters":
                record.progress_percent = 35.0
            elif record.processing_phase == "documents":
                total = record.total_document_count or 1
                record.progress_percent = min(
                    99.0,
                    35.0
                    + 64.0 * record.processed_document_count / total,
                )
            elif record.processing_phase == "finalize":
                record.progress_percent = 99.0
            elif record.state == "parsed":
                record.progress_percent = 30.0
            else:
                record.progress_percent = 0.0

    # ------------------------------------------------------------------
    # Log en memoria durante un lote
    # ------------------------------------------------------------------
    def _append_log(self, message):
        buffer = self.env.context.get("suenlace_log_buffer")
        if isinstance(buffer, list):
            text = str(message)
            buffer.append(text)
            _logger.info(
                "[SUENLACE %(name)s] %(msg)s",
                {"name": self.display_name, "msg": text},
            )
            return
        return super()._append_log(message)

    def _flush_log_buffer(self, messages):
        self.ensure_one()
        if not messages:
            return
        current = self.log or ""
        chunk = "\n".join(messages) + "\n"
        # El log es trazabilidad, pero no debe crecer indefinidamente hasta
        # convertir cada escritura en una operación costosa.
        max_chars = 2_000_000
        new_log = (current + chunk)[-max_chars:]
        self.with_context(suenlace_log_buffer=None).write({"log": new_log})

    # ------------------------------------------------------------------
    # Serialización de registros parseados
    # ------------------------------------------------------------------
    @staticmethod
    def _json_default(value):
        if isinstance(value, (datetime.date, datetime.datetime)):
            return {"__suenlace_date__": value.isoformat()}
        raise TypeError(type(value).__name__)

    @staticmethod
    def _json_object_hook(value):
        date_value = value.get("__suenlace_date__")
        if date_value:
            return datetime.date.fromisoformat(date_value[:10])
        return value

    def _serialize_payload(self, data):
        return json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
            default=self._json_default,
        )

    def _deserialize_payload(self, payload):
        if not payload:
            return {}
        try:
            return json.loads(payload, object_hook=self._json_object_hook)
        except (json.JSONDecodeError, TypeError, ValueError):
            # Compatibilidad con lotes parseados por versiones anteriores,
            # que almacenaban repr(dict) y podían contener datetime.date().
            return safe_eval(
                payload,
                {
                    "datetime": datetime,
                    "date": datetime.date,
                },
                mode="eval",
                nocopy=True,
            )

    # ------------------------------------------------------------------
    # Acciones web: preparación rápida + worker externo
    # ------------------------------------------------------------------
    def action_parse(self):
        sync_records = self.filtered(lambda record: not record.background_mode)
        async_records = self - sync_records
        if sync_records:
            super(SuenlaceImport, sync_records).action_parse()
        for record in async_records:
            record._prepare_background_parse(requested_operation="parse")
            record._trigger_background_worker()
        return True

    def action_process(self):
        sync_records = self.filtered(lambda record: not record.background_mode)
        async_records = self - sync_records
        if sync_records:
            super(SuenlaceImport, sync_records).action_process()
        for record in async_records:
            if not record.file_data:
                raise UserError(_("Debe adjuntar un fichero SUENLACE."))
            has_lines = bool(self.env["tl.suenlace.import.line"].search_count(
                [("import_id", "=", record.id)], limit=1
            ))
            if (
                record.state == "draft"
                or not has_lines
                or (record.state == "parsed" and not record.type_count_json)
                or (record.state == "error" and not record.move_ids)
                or not record.source_company_code
            ):
                record._prepare_background_parse(
                    requested_operation="process"
                )
            else:
                record._validate_source_company_code(
                    record.source_company_code
                )
                # Reanuda solo elementos pendientes o con error. Los ya
                # procesados no vuelven a crearse.
                self.env["tl.suenlace.import.line"].search([
                    ("import_id", "=", record.id),
                    ("processing_state", "=", "error"),
                ]).write({
                    "processing_state": "pending",
                    "error_message": False,
                })
                done_documents = self.env["tl.suenlace.import.line"].search_count([
                    ("import_id", "=", record.id),
                    ("is_document_start", "=", True),
                    ("processing_state", "=", "done"),
                ])
                record.write({
                    "requested_operation": "process",
                    "processing_phase": "masters",
                    "master_cursor": 0,
                    "processed_document_count": done_documents,
                    "failed_master_count": 0,
                    "failed_document_count": 0,
                    "state": "queued",
                })
            record._trigger_background_worker()
        return True

    def action_reset_draft(self):
        for record in self:
            if record.move_ids:
                raise UserError(_(
                    "No puede reiniciar un lote que ya tiene documentos "
                    "contables. Cree una importación nueva para evitar duplicados."
                ))
            self.env["tl.suenlace.import.line"].search([
                ("import_id", "=", record.id),
            ]).unlink()
            record.write({
                "state": "draft",
                "log": "",
                "line_count": 0,
                "processing_phase": "idle",
                "requested_operation": "parse",
                "parse_cursor": 0,
                "parse_byte_offset": 0,
                "master_cursor": 0,
                "parse_document_counter": 0,
                "parse_current_document_key": False,
                "parse_current_document_type": False,
                "total_record_count": 0,
                "processed_document_count": 0,
                "total_document_count": 0,
                "failed_document_count": 0,
                "failed_master_count": 0,
                "type_count_json": False,
                "last_batch_date": False,
                "source_company_code": False,
            })
        return True

    def _prepare_background_parse(self, requested_operation="parse"):
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Debe adjuntar un fichero SUENLACE."))
        self._required_company_code()
        if self.move_ids:
            raise UserError(_(
                "Este lote ya contiene documentos creados. Para evitar "
                "duplicados, cree una importación nueva en lugar de volver "
                "a parsear el mismo lote."
            ))
        self.env["tl.suenlace.import.line"].search([
            ("import_id", "=", self.id),
        ]).unlink()
        self.write({
            "state": "queued",
            "processing_phase": "parse",
            "requested_operation": requested_operation,
            "parse_cursor": 0,
            "parse_byte_offset": 0,
            "master_cursor": 0,
            "parse_document_counter": 0,
            "parse_current_document_key": False,
            "parse_current_document_type": False,
            "total_record_count": 0,
            "processed_document_count": 0,
            "total_document_count": 0,
            "failed_document_count": 0,
            "failed_master_count": 0,
            "type_count_json": "{}",
            "line_count": 0,
            "log": "",
            "last_batch_date": False,
            "source_company_code": False,
        })

    def _trigger_background_worker(self):
        """Activa el worker nativo.

        El addon opcional de Queue Job sobreescribe este método y encola el
        mismo ``job_run_batch``. El módulo base no depende de queue_job.
        """
        cron = self.env.ref(
            "tl_suenlace_import.ir_cron_suenlace_background",
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()

    # ------------------------------------------------------------------
    # Worker nativo y método compartido con queue_job
    # ------------------------------------------------------------------
    @api.model
    def _native_worker_domain(self):
        return [
            ("state", "in", ("queued", "processing")),
            ("processing_phase", "!=", "idle"),
        ]

    @api.model
    def _cron_process_pending_imports(self):
        domain = self._native_worker_domain()
        company_ids = self.env["res.company"].sudo().search([]).ids
        worker_model = self.sudo().with_context(
            allowed_company_ids=company_ids,
            force_company=False,
        )
        records = worker_model.search(
            domain, order="create_date, id", limit=10
        )
        cron_model = self.env["ir.cron"]
        if not records:
            cron_model._commit_progress(remaining=0)
            return

        for record in records:
            try:
                with self.env.cr.savepoint():
                    record.job_run_batch(trigger_next=False)
            except Exception as exc:  # noqa: BLE001
                _logger.exception(
                    "Error no controlado en lote SUENLACE %s", record.id
                )
                record.write({
                    "state": "error",
                    "processing_phase": "idle",
                })
                record._append_log(_("ERROR NO CONTROLADO: %s") % exc)
            remaining = worker_model.search_count(domain)
            seconds = cron_model._commit_progress(
                processed=1,
                remaining=remaining,
            )
            if not seconds:
                break

    def job_run_batch(self, trigger_next=True):
        """Procesa como máximo un lote pequeño y retorna.

        Cada llamada es transaccional. Si el worker se interrumpe, el lote se
        reanuda desde los cursores persistidos sin repetir documentos ya
        confirmados como procesados.
        """
        self.ensure_one()
        record = self.with_company(self.company_id).with_context(
            allowed_company_ids=[self.company_id.id],
            force_company=self.company_id.id,
        )
        if record.state not in ("queued", "processing"):
            return False
        if record.processing_phase != "parse" and record.source_company_code:
            record._validate_source_company_code(record.source_company_code)

        messages = []
        worker = record.with_context(suenlace_log_buffer=messages)
        processed = False
        try:
            worker.write({
                "state": "processing",
                "last_batch_date": fields.Datetime.now(),
            })
            phase = worker.processing_phase
            if phase == "parse":
                processed = worker._run_parse_batch()
            elif phase == "masters":
                processed = worker._run_master_batch()
            elif phase == "documents":
                processed = worker._run_document_batch()
            elif phase == "finalize":
                processed = worker._run_finalize_batch()
            else:
                worker.write({"state": "error", "processing_phase": "idle"})
                worker._append_log(_("Fase de procesamiento desconocida."))
        except UserError as exc:
            worker.write({"state": "error", "processing_phase": "idle"})
            worker._append_log(_("ERROR DE VALIDACIÓN: %s") % exc)
            processed = False
        finally:
            record._flush_log_buffer(messages)

        if (
            trigger_next
            and record.state in ("queued", "processing")
            and record.processing_phase != "idle"
        ):
            record._trigger_background_worker()
        return processed

    # ------------------------------------------------------------------
    # Parseo incremental
    # ------------------------------------------------------------------
    @staticmethod
    def _has_line_breaks(raw):
        # BytesIO.readline separa por LF. Los ficheros normales usan CRLF;
        # si no hay LF se trata como formato fijo de 512 bytes.
        return b"\n" in raw

    @staticmethod
    def _count_raw_records(raw, line_mode):
        if not raw:
            return 0
        if not line_mode:
            return int(math.ceil(len(raw) / parser.RECORD_LENGTH))
        # El formato normal termina cada registro con CRLF.
        lf_count = raw.count(b"\n")
        if lf_count:
            return lf_count + (0 if raw.endswith(b"\n") else 1)
        cr_count = raw.count(b"\r")
        return cr_count + (0 if raw.endswith(b"\r") else 1)

    def _iter_raw_slice(self, raw, start_offset, limit, line_mode):
        if line_mode:
            stream = io.BytesIO(raw)
            stream.seek(start_offset)
            yielded = 0
            while yielded < limit:
                raw_line = stream.readline()
                if not raw_line:
                    break
                yielded += 1
                yield raw_line.rstrip(b"\r\n"), stream.tell()
            return

        offset = start_offset
        yielded = 0
        while offset < len(raw) and yielded < limit:
            next_offset = min(offset + parser.RECORD_LENGTH, len(raw))
            raw_line = raw[offset:next_offset]
            offset = next_offset
            yielded += 1
            yield raw_line.rstrip(b"\r\n"), offset

    def _document_metadata_for_record(
        self,
        data,
        counter,
        current_key,
        current_type,
    ):
        rtype = data.get("_type")
        is_start = False
        assigned_key = False
        assigned_type = False

        if rtype in ("1", "2"):
            counter += 1
            current_key = "INV-%09d" % counter
            current_type = "invoice"
            assigned_key = current_key
            assigned_type = current_type
            is_start = True
        elif rtype == "0":
            if (
                current_type != "entry"
                or not current_key
                or data.get("linea") == "I"
            ):
                counter += 1
                current_key = "ENT-%09d" % counter
                current_type = "entry"
                is_start = True
            assigned_key = current_key
            assigned_type = current_type
            if data.get("linea") == "U":
                current_key = False
                current_type = False
        elif (
            current_type == "invoice"
            and current_key
            and rtype in INVOICE_CHILD_TYPES
        ):
            assigned_key = current_key
            assigned_type = current_type

        return (
            counter,
            current_key,
            current_type,
            assigned_key,
            assigned_type,
            is_start,
        )

    def _run_parse_batch(self):
        self.ensure_one()
        raw = base64.b64decode(self.file_data or b"")
        if not raw:
            self.write({"state": "error", "processing_phase": "idle"})
            self._append_log(_("El fichero SUENLACE está vacío."))
            return False

        line_mode = self._has_line_breaks(raw)
        total = self.total_record_count or self._count_raw_records(
            raw, line_mode
        )
        encoding = self.encoding or parser.detect_encoding(raw)
        if not self.encoding:
            self.encoding = encoding

        limit = max(1, self.parse_batch_size or DEFAULT_PARSE_BATCH_SIZE)
        sequence = self.parse_cursor
        offset = self.parse_byte_offset
        counter = self.parse_document_counter
        current_key = self.parse_current_document_key or False
        current_type = self.parse_current_document_type or False
        type_counts = json.loads(self.type_count_json or "{}")
        detected_company_code = self.source_company_code or False
        values = []
        last_offset = offset

        for raw_line, next_offset in self._iter_raw_slice(
            raw, offset, limit, line_mode
        ):
            last_offset = next_offset
            if not raw_line.strip():
                continue
            sequence += 1
            try:
                text = raw_line.decode(encoding, errors="replace")
            except LookupError:
                text = raw_line.decode("cp1252", errors="replace")
            data = parser.parse_line(text)
            if data is None:
                continue
            detected_company_code = self._validate_source_company_code(
                data.get("empresa"),
                sequence=sequence,
                detected_code=detected_company_code,
            )
            rtype = data.get("_type") or "?"
            type_counts[rtype] = type_counts.get(rtype, 0) + 1
            (
                counter,
                current_key,
                current_type,
                document_key,
                document_type,
                is_start,
            ) = self._document_metadata_for_record(
                data,
                counter,
                current_key,
                current_type,
            )
            values.append({
                "import_id": self.id,
                "sequence": sequence,
                "record_type": rtype,
                "source_company_code": detected_company_code,
                "payload": self._serialize_payload(data),
                "unsupported": bool(data.get("_unsupported")),
                "document_key": document_key or False,
                "document_type": document_type or False,
                "is_document_start": is_start,
                "processing_state": "pending",
            })

        if values:
            self.env["tl.suenlace.import.line"].create(values)

        eof = last_offset >= len(raw)
        update_values = {
            "parse_cursor": sequence,
            "parse_byte_offset": last_offset,
            "parse_document_counter": counter,
            "parse_current_document_key": current_key or False,
            "parse_current_document_type": current_type or False,
            "total_record_count": total,
            "total_document_count": counter,
            "type_count_json": json.dumps(type_counts, sort_keys=True),
            "line_count": self.line_count + len(values),
            "source_company_code": detected_company_code or False,
        }
        if eof:
            update_values.update({
                "parse_current_document_key": False,
                "parse_current_document_type": False,
            })
            summary = ", ".join(
                "%s=%s" % (key, value)
                for key, value in sorted(type_counts.items())
            )
            self._append_log(_(
                "Empresa SUENLACE validada: %(code)s → %(company)s."
            ) % {
                "code": detected_company_code,
                "company": self.company_id.display_name,
            })
            self._append_log(
                _("Parseados %(records)d registros en %(documents)d "
                  "documentos: %(summary)s") % {
                    "records": sequence,
                    "documents": counter,
                    "summary": summary,
                }
            )
            if self.requested_operation == "process":
                update_values.update({
                    "state": "processing",
                    "processing_phase": "masters",
                    "master_cursor": 0,
                })
            else:
                update_values.update({
                    "state": "parsed",
                    "processing_phase": "idle",
                })
        self.write(update_values)
        return bool(values)

    # ------------------------------------------------------------------
    # Cuentas y partners por lotes
    # ------------------------------------------------------------------
    def _run_master_batch(self):
        self.ensure_one()
        line_model = self.env["tl.suenlace.import.line"]
        lines = line_model.search(
            [
                ("import_id", "=", self.id),
                ("record_type", "in", MASTER_RECORD_TYPES),
                ("processing_state", "=", "pending"),
                ("sequence", ">", self.master_cursor),
            ],
            order="sequence, id",
            limit=max(1, self.batch_size or DEFAULT_BATCH_SIZE),
        )
        if not lines:
            self.write({
                "processing_phase": "documents",
                "master_cursor": 0,
            })
            self._append_log(_("Finalizado el tratamiento de cuentas y terceros."))
            return False

        failed = 0
        last_sequence = self.master_cursor
        for line in lines:
            last_sequence = max(last_sequence, line.sequence)
            try:
                with self.env.cr.savepoint():
                    data = self._deserialize_payload(line.payload)
                    self._process_accounts_partners([data])
                line.write({
                    "processing_state": "done",
                    "error_message": False,
                })
            except Exception as exc:  # noqa: BLE001
                failed += 1
                line.write({
                    "processing_state": "error",
                    "error_message": str(exc),
                })
                self._append_log(
                    _("Error en registro maestro %(sequence)s: %(error)s") % {
                        "sequence": line.sequence,
                        "error": exc,
                    }
                )
        self.write({
            "master_cursor": last_sequence,
            "failed_master_count": self.failed_master_count + failed,
        })
        return True

    # ------------------------------------------------------------------
    # Documentos por lotes
    # ------------------------------------------------------------------
    def _post_move_if_allowed(self, move):
        if not self.post_moves or not move or move.state != "draft":
            return
        requires_review = any([
            move.suenlace_needs_review,
            move.suenlace_fiscal_needs_review,
            move.suenlace_partner_needs_review,
            move.suenlace_tax_needs_review,
            move.suenlace_payment_needs_review,
        ])
        if not requires_review:
            move.action_post()

    def _process_one_document(self, start_line):
        document_lines = self.env["tl.suenlace.import.line"].search(
            [
                ("import_id", "=", self.id),
                ("document_key", "=", start_line.document_key),
            ],
            order="sequence, id",
        )
        records = [
            self._deserialize_payload(line.payload) for line in document_lines
        ]
        if not records:
            raise UserError(_("Documento SUENLACE vacío."))

        if start_line.document_type == "invoice":
            move = (
                self._create_invoice(records)
                if self.associate_taxes
                else self._create_invoice_as_literal_entry(records)
            )
        else:
            entry_records = [
                record for record in records if record.get("_type") == "0"
            ]
            if not entry_records or entry_records[-1].get("linea") != "U":
                raise UserError(_(
                    "Asiento incompleto: falta la línea final U."
                ))
            move = self._create_entry(entry_records)

        if move:
            self._prepare_suenlace_document(move, records)
            self._post_move_if_allowed(move)
            self._finalize_suenlace_document(move, records)
            self.write({
                "move_ids": [(4, move.id)],
                "move_count": self.move_count + 1,
            })
        document_lines.write({
            "processing_state": "done",
            "error_message": False,
        })
        return move

    def _run_document_batch(self):
        self.ensure_one()
        line_model = self.env["tl.suenlace.import.line"]
        starts = line_model.search(
            [
                ("import_id", "=", self.id),
                ("is_document_start", "=", True),
                ("processing_state", "=", "pending"),
            ],
            order="sequence, id",
            limit=max(1, self.batch_size or DEFAULT_BATCH_SIZE),
        )
        if not starts:
            self.write({"processing_phase": "finalize"})
            return False

        failed = 0
        completed = 0
        for start_line in starts:
            try:
                with self.env.cr.savepoint():
                    self._process_one_document(start_line)
                completed += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                document_lines = line_model.search([
                    ("import_id", "=", self.id),
                    ("document_key", "=", start_line.document_key),
                ])
                document_lines.write({
                    "processing_state": "error",
                    "error_message": str(exc),
                })
                self._append_log(
                    _("Error en documento %(document)s: %(error)s") % {
                        "document": start_line.document_key,
                        "error": exc,
                    }
                )

        self.write({
            "processed_document_count": (
                self.processed_document_count + completed + failed
            ),
            "failed_document_count": self.failed_document_count + failed,
        })
        self._append_log(
            _("Lote contable: %(ok)d documentos creados y %(failed)d con "
              "error.") % {"ok": completed, "failed": failed}
        )
        return True

    def _run_finalize_batch(self):
        self.ensure_one()
        n_count = self.env["tl.suenlace.import.line"].search_count([
            ("import_id", "=", self.id),
            ("record_type", "=", "N"),
        ])
        if n_count:
            self._append_log(
                _("%(count)d registros de modelo 190 quedaron parseados; "
                  "su generación requiere el módulo correspondiente.") % {
                    "count": n_count,
                }
            )
        failed = self.failed_master_count + self.failed_document_count
        self.write({
            "state": "error" if failed else "done",
            "processing_phase": "idle",
        })
        if failed:
            self._append_log(
                _("Proceso finalizado con %(count)d errores. Los documentos "
                  "correctos se conservaron y los fallidos pueden reintentarse.")
                % {"count": failed}
            )
        else:
            self._append_log(_("Importación SUENLACE finalizada correctamente."))
        return True


class SuenlaceImportLine(models.Model):
    _inherit = "tl.suenlace.import.line"

    document_key = fields.Char(string="Documento", index=True, copy=False)
    document_type = fields.Selection(
        [("invoice", "Factura"), ("entry", "Asiento")],
        string="Tipo de documento",
        index=True,
        copy=False,
    )
    is_document_start = fields.Boolean(index=True, copy=False)
    processing_state = fields.Selection(
        [
            ("pending", "Pendiente"),
            ("done", "Procesado"),
            ("error", "Error"),
        ],
        default="pending",
        required=True,
        index=True,
        copy=False,
    )
    error_message = fields.Text(string="Error", copy=False)
