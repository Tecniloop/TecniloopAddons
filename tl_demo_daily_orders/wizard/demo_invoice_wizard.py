# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TlDemoInvoiceWizard(models.TransientModel):
    _name = "tl.demo.invoice.wizard"
    _description = "Facturar pedidos demo el mismo día"

    date_from = fields.Date(
        string="Fecha desde",
        required=True,
        default=lambda s: fields.Date.today() - timedelta(days=14),
    )
    date_to = fields.Date(string="Fecha hasta", required=True, default=fields.Date.today)
    company_id = fields.Many2one(
        "res.company", string="Compañía", default=lambda s: s.env.company, required=True
    )
    invoice_sales = fields.Boolean(string="Facturar ventas", default=True)
    invoice_purchases = fields.Boolean(string="Facturar compras", default=True)
    sale_journal_id = fields.Many2one(
        "account.journal",
        string="Diario de ventas",
        domain="[('type', '=', 'sale'), ('company_id', '=', company_id)]",
        help="Si lo dejas vacío se usa el diario por defecto. Elige otro para no mezclar numeración.",
    )
    purchase_journal_id = fields.Many2one(
        "account.journal",
        string="Diario de compras",
        domain="[('type', '=', 'purchase'), ('company_id', '=', company_id)]",
        help="Opcional. Mismo criterio que el diario de ventas.",
    )
    use_queue_job = fields.Boolean(
        string="Usar cola de trabajos (un job por día)",
        default=True,
        help="Recomendado en intervalos largos. Requiere queue_job y un worker.",
    )
    last_summary = fields.Text(string="Resultado", readonly=True)

    def _days(self):
        day = self.date_from
        while day <= self.date_to:
            yield day
            day += timedelta(days=1)

    def action_invoice(self):
        self.ensure_one()
        if self.date_to < self.date_from:
            raise UserError(_("La fecha hasta no puede ser anterior a la fecha desde."))
        if not self.invoice_sales and not self.invoice_purchases:
            raise UserError(_("Marca al menos ventas o compras."))

        generator = self.env["tl.demo.orders.generator"]
        use_job = self.use_queue_job and hasattr(generator, "with_delay")
        if self.use_queue_job and not hasattr(generator, "with_delay"):
            raise UserError(
                _("La cola de trabajos no está disponible. Instala queue_job o desmarca la opción.")
            )

        queued = 0
        for day in self._days():
            opts = {
                "company_id": self.company_id.id,
                "invoice_sales": self.invoice_sales,
                "invoice_purchases": self.invoice_purchases,
                "sale_journal_id": self.sale_journal_id.id if self.sale_journal_id else False,
                "purchase_journal_id": self.purchase_journal_id.id if self.purchase_journal_id else False,
            }
            if use_job:
                generator.with_delay(
                    description=_("Facturas demo %(day)s") % {"day": day},
                    max_retries=3,
                )._invoice_day(str(day), opts)
            else:
                generator._invoice_day(str(day), opts)
            queued += 1

        if use_job:
            self.last_summary = _(
                "Se han encolado %(jobs)s trabajos de facturación entre %(start)s y %(end)s."
            ) % {"jobs": queued, "start": self.date_from, "end": self.date_to}
            if "queue.job" in self.env:
                return {
                    "type": "ir.actions.act_window",
                    "name": _("Trabajos de facturas demo"),
                    "res_model": "queue.job",
                    "view_mode": "list,form",
                    "domain": [("name", "ilike", "Facturas demo")],
                    "target": "current",
                }
        else:
            self.last_summary = _(
                "Facturación síncrona de %(days)s días entre %(start)s y %(end)s."
            ) % {"days": queued, "start": self.date_from, "end": self.date_to}
        return {"type": "ir.actions.act_window_close"}
