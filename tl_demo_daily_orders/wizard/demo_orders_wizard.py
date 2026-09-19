# -*- coding: utf-8 -*-
import logging
import random
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TlDemoOrdersWizard(models.TransientModel):
    _name = "tl.demo.orders.wizard"
    _description = "Generar pedidos de compra y venta demo por fechas"

    date_from = fields.Date(
        string="Fecha desde",
        required=True,
        default=lambda s: fields.Date.today() - timedelta(days=14),
    )
    date_to = fields.Date(string="Fecha hasta", required=True, default=fields.Date.today)
    min_per_day = fields.Integer(string="Mínimo de pedidos por día", default=3, required=True)
    max_per_day = fields.Integer(string="Máximo de pedidos por día", default=7, required=True)
    lines_min = fields.Integer(string="Líneas mínimas por pedido", default=1)
    lines_max = fields.Integer(string="Líneas máximas por pedido", default=4)
    company_id = fields.Many2one(
        "res.company", string="Compañía", default=lambda s: s.env.company, required=True
    )
    warehouse_id = fields.Many2one("stock.warehouse", string="Almacén")
    generate_confirmed = fields.Boolean(
        string="Pedidos confirmados",
        default=True,
        help="Pedidos de venta y compra confirmados (comportamiento actual).",
    )
    generate_sale_quotes = fields.Boolean(
        string="Presupuestos de venta",
        default=True,
        help="Presupuestos en borrador o enviado, sin confirmar ni albarán.",
    )
    generate_purchase_rfqs = fields.Boolean(
        string="Presupuestos de compra (RFQ)",
        default=True,
        help="Solicitudes de presupuesto en borrador o enviado, sin confirmar.",
    )
    validate_deliveries_by_date = fields.Boolean(
        string="Validar entregas según fecha",
        default=True,
        help="Marcado: valida recepciones y entregas con fecha efectiva = día del pedido. "
             "Desmarcado: deja los albaranes pendientes (listos para servir/recibir) "
             "con fecha prevista = fecha del pedido.",
    )
    confirm_pickings = fields.Boolean(string="Validar albaranes", default=True)
    backdate_pickings = fields.Boolean(
        string="Fecha efectiva pasada (Odoo 19)",
        default=True,
        help="Desbloquea el albarán, escribe la fecha efectiva y vuelve a bloquearlo.",
    )
    use_queue_job = fields.Boolean(
        string="Usar cola de trabajos (un job por día)",
        default=True,
        help="Recomendado si el intervalo es largo. Requiere el módulo queue_job y un worker.",
    )
    user_ids = fields.Many2many(
        "res.users",
        "tl_demo_orders_wizard_user_rel",
        "wizard_id",
        "user_id",
        string="Comerciales / responsables",
        help="Se asignan al azar en cada pedido y albarán. Por defecto todos los usuarios internos.",
    )
    last_summary = fields.Text(string="Resultado", readonly=True)

    @api.model
    def _default_users(self):
        return self.env["res.users"].search(
            [("share", "=", False), ("active", "=", True), ("id", "!=", 1)]
        )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        wh = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        if wh and "warehouse_id" in fields_list:
            res["warehouse_id"] = wh.id
        if "user_ids" in fields_list and not res.get("user_ids"):
            res["user_ids"] = [(6, 0, self._default_users().ids)]
        return res

    def _days(self):
        day = self.date_from
        while day <= self.date_to:
            yield day
            day += timedelta(days=1)

    def _opts(self, count):
        return {
            "count": count,
            "company_id": self.company_id.id,
            "warehouse_id": self.warehouse_id.id if self.warehouse_id else False,
            "confirm_pickings": self.validate_deliveries_by_date,
            "backdate_pickings": self.validate_deliveries_by_date and self.backdate_pickings,
            "schedule_only": not self.validate_deliveries_by_date,
            "lines_min": self.lines_min,
            "lines_max": self.lines_max,
            "user_ids": self.user_ids.ids or self._default_users().ids,
            "generate_confirmed": self.generate_confirmed,
            "generate_sale_quotes": self.generate_sale_quotes,
            "generate_purchase_rfqs": self.generate_purchase_rfqs,
        }

    def action_generate(self):
        self.ensure_one()
        if self.date_to < self.date_from:
            raise UserError(_("La fecha hasta no puede ser anterior a la fecha desde."))
        if self.min_per_day < 1 or self.max_per_day < self.min_per_day:
            raise UserError(_("Revisa el intervalo de pedidos por día."))
        if not self.user_ids:
            raise UserError(_("Selecciona al menos un usuario para comercial y responsable."))
        if not (self.generate_confirmed or self.generate_sale_quotes or self.generate_purchase_rfqs):
            raise UserError(_("Marca al menos un tipo de documento."))

        generator = self.env["tl.demo.orders.generator"]
        if not generator._customers(self.company_id.id):
            raise UserError(_("No hay contactos con rango de cliente."))
        if not generator._products(self.company_id.id):
            raise UserError(_("No hay productos almacenables o consumibles activos."))

        days = list(self._days())
        queued = 0
        use_job = self.use_queue_job and hasattr(generator, "with_delay")
        if self.use_queue_job and not hasattr(generator, "with_delay"):
            raise UserError(
                _("La cola de trabajos no está disponible. Instala queue_job o desmarca la opción.")
            )

        for day in days:
            count = random.randint(self.min_per_day, self.max_per_day)
            opts = self._opts(count)
            if use_job:
                generator.with_delay(
                    description=_("Pedidos demo %(day)s (%(count)s pedidos)")
                    % {"day": day, "count": count},
                    max_retries=3,
                )._generate_day(str(day), opts)
                queued += 1
            else:
                generator._generate_day(str(day), opts)
                queued += 1

        if use_job:
            summary = _(
                "Se han encolado %(jobs)s trabajos (un día cada uno) entre %(start)s y %(end)s. "
                "Revisa Cola de trabajos."
            ) % {"jobs": queued, "start": self.date_from, "end": self.date_to}
        else:
            summary = _("Generación síncrona de %(days)s días entre %(start)s y %(end)s.") % {
                "days": queued,
                "start": self.date_from,
                "end": self.date_to,
            }
        self.last_summary = summary
        _logger.info(summary)

        if use_job and "queue.job" in self.env:
            return {
                "type": "ir.actions.act_window",
                "name": _("Trabajos de pedidos demo"),
                "res_model": "queue.job",
                "view_mode": "list,form",
                "domain": [("name", "ilike", "Pedidos demo")],
                "target": "current",
            }
        return {"type": "ir.actions.act_window_close"}
