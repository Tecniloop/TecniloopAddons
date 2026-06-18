/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Component } from "@odoo/owl";

// -------------------
// Custom Screen
// -------------------
class SaleOrderScreen extends Component {
    setup() {
        this.dialog = useService("dialog");
        this.orm = this.env.services.orm;
        this.saleOrders = [];
        this.loadOrders();
    }

    async loadOrders() {
        this.saleOrders = await this.orm.call("sale.order", "search_read", [
            [],
            ["id", "name", "partner_id", "state", "amount_total"],
        ]);
        this.render();
    }

    async confirmOrder(order) {
        await this.orm.call("sale.order", "action_confirm", [order.id]);
        this.dialog.add(ConfirmationDialog, {
            title: _t("Confirmed"),
            body: _t(`${order.name} has been confirmed.`),
        });
        await this.loadOrders();
    }

    async cancelOrder(order) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Cancel Confirmation"),
            body: _t(`Are you sure you want to cancel ${order.name}?`),
            confirmLabel: _t("Yes, Cancel"),
            cancelLabel: _t("No"),
            confirm: async () => {
                await this.orm.call("sale.order", "action_cancel", [order.id], {
                    context: { disable_cancel_warning: true },
                });
                await this.loadOrders();
            },
        });
    }
}
SaleOrderScreen.template = "pos_sale_order_screen";

// -------------------
// Register Screen
// -------------------
registry.category("pos_screens").add("SaleOrderScreen", SaleOrderScreen);
