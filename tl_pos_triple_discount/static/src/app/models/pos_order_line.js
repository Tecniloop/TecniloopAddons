import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { parseFloat } from "@web/views/fields/parsers";
import { patch } from "@web/core/utils/patch";

function parseDiscount(value) {
    const parsed = typeof value === "number" ? value : isNaN(parseFloat(value)) ? 0 : parseFloat("" + value);
    // Keep Odoo's upper limit, but allow negative discounts as surcharges,
    // matching sale_triple_discount behaviour.
    return Math.min(parsed || 0, 100);
}

for (const fieldName of ["discount2", "discount3", "discounting_type"]) {
    PosOrderline.accountingFields?.add?.(fieldName);
}

patch(PosOrderline.prototype, {
    setup(vals) {
        super.setup(...arguments);
        if (this.sale_order_line_id && Object.hasOwn(this.sale_order_line_id, "discount1")) {
            this.discount = parseDiscount(
                this.discount ?? vals?.discount ?? this.sale_order_line_id.discount1 ?? 0
            );
        }
        this.discount2 = parseDiscount(
            this.discount2 ?? vals?.discount2 ?? this.sale_order_line_id?.discount2 ?? 0
        );
        this.discount3 = parseDiscount(
            this.discount3 ?? vals?.discount3 ?? this.sale_order_line_id?.discount3 ?? 0
        );
        this.discounting_type =
            this.discounting_type ||
            vals?.discounting_type ||
            this.sale_order_line_id?.discounting_type ||
            "multiplicative";
    },

    setDiscount(discount) {
        this.discount = parseDiscount(discount);
        this.order_id?.triggerRecomputeAllPrices?.();
    },

    setDiscount2(discount) {
        this.discount2 = parseDiscount(discount);
        this.order_id?.triggerRecomputeAllPrices?.();
    },

    setDiscount3(discount) {
        this.discount3 = parseDiscount(discount);
        this.order_id?.triggerRecomputeAllPrices?.();
    },

    setDiscountingType(discountingType) {
        this.discounting_type = ["additive", "multiplicative"].includes(discountingType)
            ? discountingType
            : "multiplicative";
        this.order_id?.triggerRecomputeAllPrices?.();
    },

    _discountFields() {
        return ["discount", "discount2", "discount3"];
    },

    _additiveDiscount() {
        const total = this._discountFields().reduce(
            (sum, fieldName) => sum + (this[fieldName] || 0),
            0
        );
        return Math.min(Math.max(total, 0), 100);
    },

    _multiplicativeDiscount() {
        let discountFactor = 1;
        for (const fieldName of this._discountFields()) {
            discountFactor *= 1 - (this[fieldName] || 0) / 100;
        }
        return 100 * (1 - discountFactor);
    },

    getFinalDiscount() {
        return this.discounting_type === "additive"
            ? this._additiveDiscount()
            : this._multiplicativeDiscount();
    },

    getDiscount() {
        return this.getFinalDiscount();
    },

    getDiscountStr() {
        if (!this.hasTripleDiscount()) {
            return this.discount ? this.discount.toString() : "";
        }
        return this.getDiscountBreakdownStr() || "";
    },

    hasTripleDiscount() {
        return Boolean(this.discount2 || this.discount3 || this.discounting_type === "additive");
    },

    getDiscountBreakdownStr() {
        const values = [this.discount || 0, this.discount2 || 0, this.discount3 || 0];
        if (!values.some((value) => value)) {
            return "";
        }
        const separator = this.discounting_type === "additive" ? " + " : " x ";
        const detailed = values.map((value) => `${value}%`).join(separator);
        const finalDiscount = this.getFinalDiscount();
        const roundedFinal = Math.round((finalDiscount + Number.EPSILON) * 10000) / 10000;
        return `${detailed} = ${roundedFinal}%`;
    },

    canBeMergedWith(orderline) {
        return (
            super.canBeMergedWith(...arguments) &&
            (this.discount2 || 0) === (orderline.discount2 || 0) &&
            (this.discount3 || 0) === (orderline.discount3 || 0) &&
            (this.discounting_type || "multiplicative") ===
                (orderline.discounting_type || "multiplicative")
        );
    },
});
