# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import api, fields, models, _


class SuenlaceImport(models.Model):
    _inherit = "tl.suenlace.import"

    async_mode = fields.Boolean(
        string="Usar OCA Queue Job",
        default=True,
        help=(
            "Usa Queue Job para ejecutar cada lote. Si se desmarca, se usa "
            "el cron nativo incluido en el módulo base. En ambos casos el "
            "procesamiento sigue siendo incremental y no bloquea la petición web."
        ),
    )
    job_count = fields.Integer(compute="_compute_job_count", string="Jobs")
    job_uuids = fields.Char(
        string="UUIDs de jobs",
        copy=False,
        help="UUID de los jobs de Queue Job creados para este lote.",
    )

    @api.depends("job_uuids")
    def _compute_job_count(self):
        job_model = self.env["queue.job"].sudo()
        for record in self:
            uuids = record._job_uuid_list()
            record.job_count = (
                job_model.search_count([("uuid", "in", uuids)])
                if uuids else 0
            )

    def _job_uuid_list(self):
        self.ensure_one()
        return [uuid for uuid in (self.job_uuids or "").split(",") if uuid]

    def _register_job(self, job):
        self.ensure_one()
        if not job or not getattr(job, "uuid", None):
            return
        uuids = self._job_uuid_list()
        if job.uuid not in uuids:
            uuids.append(job.uuid)
            self.job_uuids = ",".join(uuids[-200:])

    @api.model
    def _native_worker_domain(self):
        domain = super()._native_worker_domain()
        return domain + [("async_mode", "=", False)]

    def _trigger_background_worker(self):
        native_records = self.filtered(lambda record: not record.async_mode)
        queue_records = self - native_records
        if native_records:
            super(SuenlaceImport, native_records)._trigger_background_worker()
        for record in queue_records:
            if record.processing_phase == "parse":
                cursor = "%s_%s" % (
                    record.parse_cursor,
                    record.parse_byte_offset,
                )
            elif record.processing_phase == "masters":
                cursor = record.master_cursor
            else:
                cursor = record.processed_document_count
            identity = "tl_suenlace_batch_%s_%s_%s" % (
                record.id,
                record.processing_phase,
                cursor,
            )
            job = record.with_delay(
                description=_("Procesar lote SUENLACE %s") % record.name,
                identity_key=identity,
            ).job_run_batch()
            record._register_job(job)

    def action_view_jobs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Jobs de importación"),
            "res_model": "queue.job",
            "view_mode": "list,form",
            "domain": [("uuid", "in", self._job_uuid_list())],
        }
