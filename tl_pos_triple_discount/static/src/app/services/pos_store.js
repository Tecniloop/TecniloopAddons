import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";

patch(PosStore.prototype, {
    addLineToCurrentOrder(vals, opt = {}, configure = true) {
        const saleOrderLine = vals.sale_order_line_id;
        if (saleOrderLine) {
            const hasSplitDiscount = Object.hasOwn(saleOrderLine, "discount1");
            const discount1 = hasSplitDiscount ? saleOrderLine.discount1 || 0 : saleOrderLine.discount || 0;
            vals.discount = discount1;
            vals.discount2 = saleOrderLine.discount2 || 0;
            vals.discount3 = saleOrderLine.discount3 || 0;
            vals.discounting_type = saleOrderLine.discounting_type || "multiplicative";

            // pos_sale later calls setDiscount(line.discount). In sale_triple_discount
            // for Odoo 19, line.discount is the aggregated discount, while POS needs
            // the first discount here to avoid applying discount2/discount3 twice.
            if (hasSplitDiscount && saleOrderLine.discount !== discount1) {
                saleOrderLine._tl_pos_aggregated_discount = saleOrderLine.discount;
                saleOrderLine.discount = discount1;
            }
        }
        return super.addLineToCurrentOrder(vals, opt, configure);
    },

    prepareSoBaseLineForTaxesComputationExtraValues(so, soLine) {
        const values = super.prepareSoBaseLineForTaxesComputationExtraValues(...arguments);
        if (soLine) {
            values.discount = this._getTripleDiscountFromSaleLine(soLine);
        }
        return values;
    },

    _getTripleDiscountFromSaleLine(soLine) {
        const discount1 = Object.hasOwn(soLine, "discount1")
            ? soLine.discount1 || 0
            : soLine.discount || 0;
        const discounts = [discount1, soLine.discount2 || 0, soLine.discount3 || 0];
        if (soLine.discounting_type === "additive") {
            const total = discounts.reduce((sum, value) => sum + value, 0);
            return Math.min(Math.max(total, 0), 100);
        }
        let discountFactor = 1;
        for (const discount of discounts) {
            discountFactor *= 1 - discount / 100;
        }
        return 100 * (1 - discountFactor);
    },
});
