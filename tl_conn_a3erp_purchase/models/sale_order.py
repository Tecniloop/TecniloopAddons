from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    purchase_total_amount = fields.Monetary(
        string="Total Compras",
        compute="_compute_totals",
        currency_field="currency_id"
    )
    purchase_total_invoiced = fields.Monetary(
        string="Total Material Facturado (a3ERP)",
        compute="_compute_totals",
        currency_field="currency_id"
    )
    labour_total_cost = fields.Monetary(
        string="Total Mano de Obra (Coste)",
        compute="_compute_totals",
        currency_field="currency_id"
    )
    
    account_analytic_account_line = fields.Many2one(
        comodel_name='account.analytic.account',
        string="Centro de Coste (Cliente)",
        compute="_compute_cost_center_analytic_id",
        store=True,
        readonly=True,
    )
    
    @api.depends('order_line.analytic_distribution')
    def _compute_cost_center_analytic_id(self):
        """
        Busca en las líneas del pedido una cuenta analítica cuyo plan sea analytic_plan_2.
        - Si en todas las linias solo hay 1 tipo de cuenta, muestra esa.
        - Si hay mas de 1 tipo de cuenta, deja el valor en blanco.
        """
        plan = self.env.ref('tl_conn_a3erp.analytic_plan_2', raise_if_not_found=False)
        def _extract_account_ids(dist):
            """
                dist puede ser:
                {'35': 100.0, '45': 100.0}
                o:
                {'35,45': 100.0}
                Devolvemos un set(int) con todos los ids encontrados.
            """
            ids = set()
            if not dist:
                return ids

            for key in dist.keys():
                # key puede ser int, str "35" o str "35,45"
                if key is None:
                    continue

                if isinstance(key, int):
                    ids.add(key)
                    continue

                if isinstance(key, str):
                    # separa por coma y limpia espacios
                    parts = [p.strip() for p in key.split(',') if p.strip()]
                    for p in parts:
                        if p.isdigit():
                            ids.add(int(p))
            return ids

        for order in self:
            order.account_analytic_account_line = False
            if not plan:
                continue

            accounts_plan = set()

            for line in order.order_line:
                dist = line.analytic_distribution or {}
                for acc_id in _extract_account_ids(dist):
                    acc = self.env['account.analytic.account'].browse(acc_id)
                    if acc.exists() and acc.plan_id.id == plan.id:
                        accounts_plan.add(acc.id)

            if len(accounts_plan) == 1:
                order.account_analytic_account_line = self.env['account.analytic.account'].browse(next(iter(accounts_plan)))
            else:
                order.account_analytic_account_line = False

    # @api.depends(
    #     'name',
    #     'order_line.qty_delivered',
    #     'order_line.purchase_price',
    #     'order_line.product_id.carac1_id',
    # )
    def _compute_totals(self):

        PurchaseOrder = self.env['purchase.order']

        origins = [s.name for s in self if s.name]
        totals_by_origin = {}
        invoiced_by_origin = {}

        if origins:
            # amount_untaxed por origin
            rg = PurchaseOrder.read_group(
                domain=[('origin', 'in', origins)],
                fields=['amount_untaxed:sum', 'origin'],
                groupby=['origin']
            )
            totals_by_origin = {r['origin']: r['amount_untaxed'] for r in rg}

            # a3erp_purchase_invoiced por origin (solo compras con id_document)
            rg2 = PurchaseOrder.read_group(
                domain=[('origin', 'in', origins), ('id_document', '!=', False)],
                fields=['a3erp_purchase_invoiced:sum', 'origin'],
                groupby=['origin']
            )
            invoiced_by_origin = {r['origin']: r['a3erp_purchase_invoiced'] for r in rg2}

        # Mano de obra 
        for sale in self:
            total_service = 0.0
            for line in sale.order_line.filtered(
                lambda l: l.qty_delivered
                and l.product_id.carac1_id
                and l.product_id.carac1_id.cod_carac in ('6', '11', '14')
            ):
                total_service += line.purchase_price * line.qty_delivered

            sale.purchase_total_amount = totals_by_origin.get(sale.name, 0.0)
            sale.purchase_total_invoiced = invoiced_by_origin.get(sale.name, 0.0)
            sale.labour_total_cost = total_service