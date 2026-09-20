# -*- coding: utf-8 -*-
import logging
import random
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TlDemoPaymentWizard(models.TransientModel):
    _name = "tl.demo.payment.wizard"
    _description = "Cobrar y pagar facturas demo"

    date_from = fields.Date(
        string="Fecha desde",
        required=True,
        default=lambda s: fields.Date.today() - timedelta(days=14),
    )
    date_to = fields.Date(string="Fecha hasta", required=True, default=fields.Date.today)
    company_id = fields.Many2one(
        "res.company", string="Compañía", default=lambda s: s.env.company, required=True
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Diario de caja / banco",
        required=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
    )
    pay_customer = fields.Boolean(string="Cobrar facturas de cliente", default=True)
    pay_vendor = fields.Boolean(string="Pagar facturas de proveedor", default=True)
    use_queue_job = fields.Boolean(
        string="Usar cola de trabajos (un job por día)",
        default=True,
    )
    last_summary = fields.Text(string="Resultado", readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "journal_id" in fields_list and not res.get("journal_id"):
            journal = self.env["account.journal"].search(
                [
                    ("type", "in", ("bank", "cash")),
                    ("company_id", "=", self.env.company.id),
                ],
                limit=1,
            )
            if journal:
                res["journal_id"] = journal.id
        return res

    def _days(self):
        day = self.date_from
        while day <= self.date_to:
            yield day
            day += timedelta(days=1)

    def action_pay(self):
        self.ensure_one()
        if self.date_to < self.date_from:
            raise UserError(_("La fecha hasta no puede ser anterior a la fecha desde."))
        if not self.pay_customer and not self.pay_vendor:
            raise UserError(_("Marca al menos cobros o pagos."))
        if not self.journal_id:
            raise UserError(_("Indica un diario de caja o banco."))

        generator = self.env["tl.demo.orders.generator"]
        use_job = self.use_queue_job and hasattr(generator, "with_delay")
        if self.use_queue_job and not hasattr(generator, "with_delay"):
            raise UserError(_("La cola de trabajos no está disponible."))

        queued = 0
        for day in self._days():
            opts = {
                "company_id": self.company_id.id,
                "journal_id": self.journal_id.id,
                "pay_customer": self.pay_customer,
                "pay_vendor": self.pay_vendor,
            }
            if use_job:
                generator.with_delay(
                    description=_("Pagos demo %(day)s") % {"day": day},
                    max_retries=3,
                )._pay_day(str(day), opts)
            else:
                generator._pay_day(str(day), opts)
            queued += 1

        self.last_summary = _(
            "Se han lanzado %(n)s días de cobros/pagos entre %(start)s y %(end)s en %(journal)s."
        ) % {
            "n": queued,
            "start": self.date_from,
            "end": self.date_to,
            "journal": self.journal_id.display_name,
        }
        if use_job and "queue.job" in self.env:
            return {
                "type": "ir.actions.act_window",
                "name": _("Trabajos de pagos demo"),
                "res_model": "queue.job",
                "view_mode": "list,form",
                "domain": [("name", "ilike", "Pagos demo")],
                "target": "current",
            }
        return {"type": "ir.actions.act_window_close"}
