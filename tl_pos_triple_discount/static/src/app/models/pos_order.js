import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    setPricelist(pricelist) {
        const result = super.setPricelist(...arguments);
        for (const line of this.getLinesToCompute()) {
            line.applyPricelistTripleDiscount?.({ force: line.tl_discount_source === "pricelist" });
        }
        return result;
    },
});
