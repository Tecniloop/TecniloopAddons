from odoo import models, fields, api
import logging
_logger = logging.getLogger(__name__)

CAMPOS_LINEFAC = ["PRCMONEDA","BASEMONEDA","UNIDADES","TIPIVA"]

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    a3erp_purchase_invoiced = fields.Monetary(
        string="Total facturado a3ERP (BASE)",
        currency_field="currency_id",
        copy=False
    )
    a3erp_purchase_invoiced_last_sync = fields.Datetime(copy=False)

    def action_sync_a3_invoiced(self):
        """Sincroniza el total facturado desde a3ERP para estas compras (solo si id_document)."""
        domain = [
            ('id_document', '!=', False),
        ]

        purchase_orders = self.search(domain)

        _logger.info("Iniciando sincronización A3 para %s pedidos", len(purchase_orders))
        
        for po in purchase_orders:
            summary = po.get_invoice_lines_summary(
                po.id_document,
                CAMPOS_LINEFAC
            )

            if summary:
                po.write({
                    'a3erp_purchase_invoiced': summary.get('total_base', 0.0),
                    'a3erp_purchase_invoiced_last_sync': fields.Datetime.now()
                })
    
    