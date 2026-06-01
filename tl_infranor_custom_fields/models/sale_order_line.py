from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta


class SaleOrderLine(models.Model):

    _inherit = 'sale.order.line'

    undelivered_qty = fields.Float(string="Cantidad NO entregada", compute='_compute_undelivered_qty', store=True)
    undelivered_subtotal = fields.Float(string="Subtotal no entregat", compute='_compute_undelivered_subtotal', store=True)

    lines_production_confirmation_date = fields.Date(string="Fecha Confirmación Fábrica")

    fecha_entrega_final = fields.Datetime(string="Fecha Entrega Final", compute='_compute_fecha_entrega_final', store=True, readonly=True)

    #campos relaciones con el pedido de compra
    fecha_confirmacion = fields.Datetime(
        string="Fecha Confirmación",
        compute='_compute_fecha_confirmacion',
        store=True,
        readonly=True,
    )

    #campo relacionado con el reposnable del producto
    product_responsible_id = fields.Many2one(
        related='product_id.product_responsible_id',
        string='Responsable de producte',
        store=True,
    )

    @api.depends('move_ids.purchase_line_id.order_id.date_approve')
    def _compute_fecha_confirmacion(self):
        for line in self:
            purchase_order = line.move_ids.purchase_line_id.order_id
            line.fecha_confirmacion = purchase_order[:1].date_approve if purchase_order else False

    @api.depends('move_ids.picking_id.state', 'move_ids.picking_id.date_done')
    def _compute_fecha_entrega_final(self):
        for line in self:
            entregas = line.move_ids.picking_id.filtered(
                lambda p: p.picking_type_code == 'outgoing' and p.state == 'done' and p.date_done
            )
            if entregas:
                line.fecha_entrega_final = max(entregas.mapped('date_done'))
            else:
                line.fecha_entrega_final = False

    def _compute_price_unit(self):
        locked = self.filtered(lambda l: l.order_id.lock_price)
        unlocked = self - locked

        # Solo recomputar líneas sin bloqueo
        if unlocked:
            super(SaleOrderLine, unlocked)._compute_price_unit()

        # Para líneas bloqueadas existentes: leer precio directamente de BD
        existing_locked = locked.filtered(lambda l: isinstance(l.id, int))
        if existing_locked:
            self.env.cr.execute(
                "SELECT id, price_unit FROM sale_order_line WHERE id IN %s",
                [tuple(existing_locked.ids)]
            )
            prices = dict(self.env.cr.fetchall())
            for line in existing_locked:
                line.price_unit = prices.get(line.id, 0.0)

        # Líneas nuevas en un pedido bloqueado: computar normalmente
        new_locked = locked - existing_locked
        if new_locked:
            super(SaleOrderLine, new_locked)._compute_price_unit()

    def write(self, vals):
        if 'price_unit' in vals or 'purchase_price' in vals:
            locked = self.filtered(lambda l: l.order_id.lock_price)
            unlocked = self - locked
            if locked:
                locked_vals = {k: v for k, v in vals.items() if k not in ('price_unit', 'purchase_price')}
                if locked_vals:
                    super(SaleOrderLine, locked).write(locked_vals)
                if unlocked:
                    super(SaleOrderLine, unlocked).write(vals)
                return True
        return super().write(vals)

    @api.depends('product_uom_qty', 'qty_delivered')
    def _compute_undelivered_qty(self):
        for line in self:
            line.undelivered_qty = line.product_uom_qty - line.qty_delivered

    @api.depends('product_uom_qty', 'qty_delivered', 'price_unit')
    def _compute_undelivered_subtotal(self):
        for line in self:
            line.undelivered_subtotal = (line.product_uom_qty - line.qty_delivered) * line.price_unit