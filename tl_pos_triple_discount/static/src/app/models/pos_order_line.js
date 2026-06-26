import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { parseFloat } from "@web/views/fields/parsers";
import { patch } from "@web/core/utils/patch";

function parseDiscount(value) {
    const parsed = typeof value === "number" ? value : isNaN(parseFloat(value)) ? 0 : parseFloat("" + value);
    // Keep Odoo's upper limit, but allow negative discounts as surcharges,
    // matching sale_triple_discount behaviour.
    return Math.min(parsed || 0, 100);
}

function hasAnyDiscount(values) {
    return values.some((value) => Boolean(value));
}

function roundDisplay(value) {
    return Math.round((value + Number.EPSILON) * 10000) / 10000;
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
        this.tl_discount_source = vals?.tl_discount_source || false;
        this.applyPricelistTripleDiscount();
    },

    setDiscount(discount) {
        this.discount = parseDiscount(discount);
        this.tl_discount_source = "manual";
        this.order_id?.triggerRecomputeAllPrices?.();
    },

    setDiscount2(discount) {
        this.discount2 = parseDiscount(discount);
        this.tl_discount_source = "manual";
        this.order_id?.triggerRecomputeAllPrices?.();
    },

    setDiscount3(discount) {
        this.discount3 = parseDiscount(discount);
        this.tl_discount_source = "manual";
        this.order_id?.triggerRecomputeAllPrices?.();
    },

    setDiscountingType(discountingType) {
        this.discounting_type = ["additive", "multiplicative"].includes(discountingType)
            ? discountingType
            : "multiplicative";
        this.tl_discount_source = "manual";
        this.order_id?.triggerRecomputeAllPrices?.();
    },

    applyPricelistTripleDiscount({ force = false } = {}) {
        if (this.sale_order_line_id || this.price_type !== "original") {
            return;
        }
        const currentValues = [this.discount || 0, this.discount2 || 0, this.discount3 || 0];
        if (!force && hasAnyDiscount(currentValues) && this.tl_discount_source !== "pricelist") {
            return;
        }
        const productTemplate = this.product_id?.product_tmpl_id;
        const pricelist = this.order_id?.pricelist_id;
        if (!productTemplate?.getPricelistTripleDiscountValues || !pricelist) {
            return;
        }
        const values = productTemplate.getPricelistTripleDiscountValues(
            pricelist,
            this.getQuantity(),
            this.getPriceExtra(),
            this.product_id
        );
        if (values.hasDiscounts) {
            this.discount = parseDiscount(values.discount);
            this.discount2 = parseDiscount(values.discount2);
            this.discount3 = parseDiscount(values.discount3);
            this.discounting_type = values.discounting_type || "multiplicative";
            this.tl_discount_source = "pricelist";
        } else if (force && this.tl_discount_source === "pricelist") {
            this.discount = 0;
            this.discount2 = 0;
            this.discount3 = 0;
            this.discounting_type = "multiplicative";
            this.tl_discount_source = false;
        }
    },

    setQuantity(quantity, keep_price) {
        const result = super.setQuantity(...arguments);
        if (result === true || result === undefined) {
            this.applyPricelistTripleDiscount({ force: this.tl_discount_source === "pricelist" });
        }
        return result;
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
        const finalDiscount = this.getFinalDiscount();
        return finalDiscount ? roundDisplay(finalDiscount).toString() : "";
    },

    hasTripleDiscount() {
        return Boolean(this.discount2 || this.discount3 || this.discounting_type === "additive");
    },

    hasDiscountBreakdown() {
        return Boolean(this.getDiscountBreakdownStr());
    },

    getDiscountBreakdownStr() {
        const values = [this.discount || 0, this.discount2 || 0, this.discount3 || 0];
        if (!hasAnyDiscount(values)) {
            return "";
        }
        if (!this.hasTripleDiscount()) {
            return `${roundDisplay(values[0])}%`;
        }
        const separator = this.discounting_type === "additive" ? " + " : " x ";
        const detailed = values.map((value) => `${roundDisplay(value)}%`).join(separator);
        const finalDiscount = roundDisplay(this.getFinalDiscount());
        return `${detailed} = ${finalDiscount}%`;
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
