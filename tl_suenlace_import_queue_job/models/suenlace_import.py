# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import api, fields, models, _

from odoo.addons.tl_suenlace_import.exceptions import SuenlaceImportError


class SuenlaceImport(models.Model):
    _inherit = "tl.suenlace.import"

    async_mode = fields.Boolean(
        string="Proceso asíncrono",
        default=True,
        help="Ejecuta el parseo y el procesado en segundo plano mediante "
             "Job Queue.",
    )
    job_count = fields.Integer(
        compute="_compute_job_count", string="Jobs"
    )
    job_uuids = fields.Char(
        string="UUIDs de jobs",
        copy=False,
        help="Lista separada por comas de los UUID de queue.job encolados "
             "por este lote.",
    )

    @api.depends("job_uuids")
    def _compute_job_count(self):
        job_model = self.env["queue.job"].sudo()
        for rec in self:
            uuids = rec._job_uuid_list()
            rec.job_count = job_model.search_count(
                [("uuid", "in", uuids)]
            ) if uuids else 0

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
            self.job_uuids = ",".join(uuids)

    def action_parse(self):
        for rec in self:
            if not rec.file_data:
                raise SuenlaceImportError(
                    _("Debe adjuntar un fichero SUENLACE."))
            if not rec.async_mode:
                rec.job_parse()
                continue
            rec.state = "queued"
            job = rec.with_delay(
                description=_("Parsear SUENLACE %s") % rec.name,
                identity_key="tl_suenlace_parse_%s" % rec.id,
            ).job_parse()
            rec._register_job(job)
        return True

    def action_process(self):
        for rec in self:
            if rec.state == "draft":
                # El parseo debe terminar antes de poder procesar el lote.
                # En una acción única se ejecuta de forma síncrona para no
                # crear una carrera entre dos jobs independientes.
                rec.job_parse()
            if not rec.async_mode:
                rec.job_process()
                continue
            rec.state = "queued"
            job = rec.with_delay(
                description=_("Procesar SUENLACE %s") % rec.name,
                identity_key="tl_suenlace_process_%s" % rec.id,
            ).job_process()
            rec._register_job(job)
        return True

    def action_view_jobs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Jobs de importación"),
            "res_model": "queue.job",
            "view_mode": "list,form",
            "domain": [("uuid", "in", self._job_uuid_list())],
        }
