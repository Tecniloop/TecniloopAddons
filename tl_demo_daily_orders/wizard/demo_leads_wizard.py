# -*- coding: utf-8 -*-
import logging
import random
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TlDemoLeadsWizard(models.TransientModel):
    _name = "tl.demo.leads.wizard"
    _description = "Generar leads demo por fechas"

    date_from = fields.Date(
        string="Fecha desde",
        required=True,
        default=lambda s: fields.Date.today() - timedelta(days=14),
    )
    date_to = fields.Date(string="Fecha hasta", required=True, default=fields.Date.today)
    min_per_day = fields.Integer(string="Mínimo de leads por día", default=3, required=True)
    max_per_day = fields.Integer(string="Máximo de leads por día", default=7, required=True)
    company_id = fields.Many2one(
        "res.company", string="Compañía", default=lambda s: s.env.company, required=True
    )
    user_ids = fields.Many2many(
        "res.users",
        "tl_demo_leads_wizard_user_rel",
        "wizard_id",
        "user_id",
        string="Comerciales",
        help="Se asignan al azar. Por defecto todos los usuarios internos.",
    )
    tag_ids = fields.Many2many(
        "crm.tag",
        "tl_demo_leads_wizard_tag_rel",
        "wizard_id",
        "tag_id",
        string="Etiquetas",
        help="Se asignan al azar (1 o varias). Por defecto todas.",
    )
    country_ids = fields.Many2many(
        "res.country",
        "tl_demo_leads_wizard_country_rel",
        "wizard_id",
        "country_id",
        string="Países",
        help="Vacío al abrir. Elige manualmente; cada lead recibe uno al azar.",
    )
    tags_min = fields.Integer(string="Etiquetas mínimas por lead", default=1)
    tags_max = fields.Integer(string="Etiquetas máximas por lead", default=3)
    use_queue_job = fields.Boolean(
        string="Usar cola de trabajos (un job por día)",
        default=True,
    )
    last_summary = fields.Text(string="Resultado", readonly=True)

    @api.model
    def _default_users(self):
        return self.env["res.users"].search(
            [("share", "=", False), ("active", "=", True), ("id", "!=", 1)]
        )

    @api.model
    def _default_tags(self):
        return self.env["crm.tag"].search([])

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "user_ids" in fields_list and not res.get("user_ids"):
            res["user_ids"] = [(6, 0, self._default_users().ids)]
        if "tag_ids" in fields_list and not res.get("tag_ids"):
            res["tag_ids"] = [(6, 0, self._default_tags().ids)]
        return res

    def _days(self):
        day = self.date_from
        while day <= self.date_to:
            yield day
            day += timedelta(days=1)

    def action_generate(self):
        self.ensure_one()
        if self.date_to < self.date_from:
            raise UserError(_("La fecha hasta no puede ser anterior a la fecha desde."))
        if self.min_per_day < 1 or self.max_per_day < self.min_per_day:
            raise UserError(_("Revisa el intervalo de leads por día."))
        if not self.user_ids:
            raise UserError(_("Selecciona al menos un comercial."))
        if self.tags_min < 0 or self.tags_max < self.tags_min:
            raise UserError(_("Revisa el número de etiquetas por lead."))

        generator = self.env["tl.demo.orders.generator"]
        use_job = self.use_queue_job and hasattr(generator, "with_delay")
        if self.use_queue_job and not hasattr(generator, "with_delay"):
            raise UserError(_("La cola de trabajos no está disponible."))

        queued = 0
        for day in self._days():
            count = random.randint(self.min_per_day, self.max_per_day)
            opts = {
                "count": count,
                "company_id": self.company_id.id,
                "user_ids": self.user_ids.ids,
                "tag_ids": self.tag_ids.ids,
                "tags_min": self.tags_min,
                "tags_max": self.tags_max,
                "country_ids": self.country_ids.ids,
            }
            if use_job:
                generator.with_delay(
                    description=_("Leads demo %(day)s") % {"day": day},
                    max_retries=3,
                )._generate_leads_day(str(day), opts)
            else:
                generator._generate_leads_day(str(day), opts)
            queued += 1

        self.last_summary = _(
            "Se han lanzado %(n)s días de leads entre %(start)s y %(end)s."
        ) % {"n": queued, "start": self.date_from, "end": self.date_to}
        if use_job and "queue.job" in self.env:
            return {
                "type": "ir.actions.act_window",
                "name": _("Trabajos de leads demo"),
                "res_model": "queue.job",
                "view_mode": "list,form",
                "domain": [("name", "ilike", "Leads demo")],
                "target": "current",
            }
        return {"type": "ir.actions.act_window_close"}
