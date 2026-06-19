/** @odoo-module */

import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { patch } from "@web/core/utils/patch";

patch(PosOrderline.prototype, {
    setup() {
    super.setup(...arguments);
    },

    getDisplayData() {
        return {
        ...super.getDisplayData(),
         product_id: this.get_product().id,
         discount_note : this.product_id.selected_category?.discount_message,
        };
    },
    getNote() {
        return this.discount_note || "";
    }
});