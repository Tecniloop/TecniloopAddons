/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog, AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";

patch(ControlButtons.prototype, {
    setup() {
        super.setup();
        this.dialogService = useService("dialog");
        this.orm = this.env.services.orm;
        this.pos = this.env.services.pos;
    },


    async clickCreateSaleOrder() {
        const order = this.pos.selectedOrder;
        if (!order) {
            this.dialogService.add(AlertDialog, {
                title: _t("Missing Order"),
                body: _t("No active order found."),
            });
            return;
        }

        const partner = order.partner_id;
        if (!partner?.id) {
            this.dialogService.add(AlertDialog, {
                title: _t("Missing Customer"),
                body: _t("Select a customer."),
            });
            return;
        }

        const lines = order.lines || [];
        if (!lines.length) {
            this.dialogService.add(AlertDialog, {
                title: _t("Missing Products"),
                body: _t("There are no products in the order."),
            });
            return;
        }

        const orderDetails = {
            partner_id: partner.id,
            lines: lines.map((line) => {
                const product = line.product || line.product_id || line.data?.product;
                return {
                    product_id: product?.id || 0,
                    name: product?.display_name || product?.name || "Unnamed Product",
                    qty: line.qty,
                    price: line.price_unit,
                    subtotal: line.price_subtotal,
                    discount: line.discount || 0,
                };
            }),
            tax_amount: order.amount_tax || order.get_total_tax?.(),
        };

        console.log("📤 Sending orderDetails:", orderDetails);

        try {
        console.log("method called",this.orm);
            const result = await this.orm.call(
                "sale.order",
                "create_saleorder_from_pos",
                [orderDetails]
            );

            console.log("🔎 Backend returned:", result);

            if (!result) {
                this.dialogService.add(AlertDialog, {
                    title: _t("Error"),
                    body: _t("Backend did not return a valid response."),
                });
                return;
            }

            const orderId = result.id || (typeof result === "number" ? result : null);
            const orderName = result.name || `SO${orderId}`;

            this.dialog.add(ConfirmationDialog, {
                title: _t("Success"),
                body: _t(`Sale Order ${orderName} created successfully!`),
                confirmLabel: _t("Confirm Order"),
                cancelLabel: _t("Close"),
                confirm: () => {
                    if (orderId) {
                        this.orm.call("sale.order", "action_confirm", [orderId]);
                    }
                },
            });

            this.pos.addNewOrder();
        } catch (err) {
            console.error("❌ Error while creating sale order:", err);
            this.dialogService.add(AlertDialog, {
                title: _t("Error"),
                body: _t("Could not create Sale Order. Check backend logs."),
            });
        }
    },
});
