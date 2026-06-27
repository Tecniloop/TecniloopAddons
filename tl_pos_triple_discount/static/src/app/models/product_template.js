import { _t } from "@web/core/l10n/translation";
import { roundPrecision } from "@web/core/utils/numbers";
import { patch } from "@web/core/utils/patch";
import { ProductTemplate } from "@point_of_sale/app/models/product_template";

const TRIPLE_DISCOUNT_RULE_TYPES = ["percentage", "formula"];

function getRuleMainDiscount(rule) {
    if (rule?.compute_price === "percentage") {
        return rule.percent_price || 0;
    }
    if (rule?.compute_price === "formula") {
        return rule.price_discount || 0;
    }
    return 0;
}

function getRuleDiscounts(rule) {
    return [getRuleMainDiscount(rule), rule?.discount2 || 0, rule?.discount3 || 0];
}

function hasRuleTripleDiscount(rule) {
    return (
        TRIPLE_DISCOUNT_RULE_TYPES.includes(rule?.compute_price) &&
        getRuleDiscounts(rule).some((discount) => Boolean(discount))
    );
}

function getRuleTripleDiscount(rule) {
    let discountFactor = 1;
    for (const discount of getRuleDiscounts(rule)) {
        discountFactor *= 1 - discount / 100;
    }
    return 100 - discountFactor * 100;
}

function shouldExposeRuleDiscounts(rule) {
    // Odoo 19 sales dropped the visible discount-policy selector. To mimic
    // sale_triple_discount + sale_pricelist_triple_discount, a POS line must
    // keep the base price and split discounts whenever the matching pricelist
    // rule carries discount values.
    return hasRuleTripleDiscount(rule);
}

patch(ProductTemplate.prototype, {
    _tlFindPricelistRule(pricelist, quantity, variant = false) {
        if (!pricelist) {
            return null;
        }
        const product = variant || false;
        const productTmpl = variant?.product_tmpl_id || this;
        let rule = null;
        if (product) {
            const productRules = pricelist.getRulesByProductId(product.id);
            rule = pricelist.findBestRule(productRules, quantity);
        }
        if (!rule) {
            const tmplRules = pricelist.getRulesByTmplId(productTmpl.id);
            rule = pricelist.findBestRule(tmplRules, quantity);
        }
        if (!rule) {
            const categoryRulesIds = pricelist.getCategoryRulesIds(productTmpl.parentCategories);
            if (categoryRulesIds.length > 0) {
                const categoryRules = this.models["product.pricelist.item"].readMany(categoryRulesIds);
                rule = pricelist.findBestRule(categoryRules, quantity);
            }
        }
        if (!rule) {
            const globalRulesIds = pricelist.getGlobalRulesIds();
            if (globalRulesIds.length > 0) {
                const globalRules = this.models["product.pricelist.item"].readMany(globalRulesIds);
                rule = pricelist.findBestRule(globalRules, quantity);
            }
        }
        return rule;
    },

    _tlGetPriceComputation(
        pricelist,
        quantity,
        price_extra = 0,
        recurring = false,
        variant = false,
        original_line = false,
        related_lines = []
    ) {
        if (recurring && !pricelist) {
            alert(
                _t(
                    "An error occurred when loading product prices.\n" +
                        "Make sure all pricelists are available in the POS."
                )
            );
        }

        const product = variant || false;
        const standardPrice = variant ? variant.standard_price : this.standard_price;
        const basePrice = variant ? variant.lst_price : this.list_price;
        let price = basePrice + (price_extra || 0);
        if (!pricelist) {
            return { price, rule: null, exposeDiscounts: false };
        }

        if (original_line && original_line.isLotTracked() && product) {
            related_lines.push(
                ...original_line.order_id.lines.filter((line) => line.product_id.id === product.id)
            );
            quantity = related_lines.reduce((sum, line) => sum + line.getQuantity(), 0);
        }

        const rule = this._tlFindPricelistRule(pricelist, quantity, variant);
        if (!rule) {
            return { price, rule: null, exposeDiscounts: false };
        }

        if (rule.base === "pricelist") {
            if (rule.base_pricelist_id) {
                price = this.getPrice(rule.base_pricelist_id, quantity, 0, true, variant);
            }
        } else if (rule.base === "standard_price") {
            price = standardPrice;
        }

        const posCurrency = this.models["pos.config"].getFirst().currency_id;
        const pricelistCurrency = pricelist.currency_id;
        const needsCurrencyConversion =
            pricelistCurrency && posCurrency && pricelistCurrency.id !== posCurrency.id;
        if (needsCurrencyConversion) {
            price *= pricelistCurrency.rate / posCurrency.rate;
        }

        const exposeDiscounts = shouldExposeRuleDiscounts(rule);
        if (rule.compute_price === "fixed") {
            price = rule.fixed_price;
        } else if (rule.compute_price === "percentage") {
            if (!exposeDiscounts) {
                price -= price * (getRuleTripleDiscount(rule) / 100);
            }
        } else {
            const price_limit = price;
            if (!exposeDiscounts) {
                price -= price * (getRuleTripleDiscount(rule) / 100);
            }
            if (rule.price_round) {
                price = roundPrecision(price, rule.price_round);
            }
            if (rule.price_surcharge) {
                price += rule.price_surcharge;
            }
            if (rule.price_min_margin) {
                price = Math.max(price, price_limit + rule.price_min_margin);
            }
            if (rule.price_max_margin) {
                price = Math.min(price, price_limit + rule.price_max_margin);
            }
        }

        if (needsCurrencyConversion) {
            price *= posCurrency.rate / pricelistCurrency.rate;
        }
        return { price, rule, exposeDiscounts };
    },

    getPrice(
        pricelist,
        quantity,
        price_extra = 0,
        recurring = false,
        variant = false,
        original_line = false,
        related_lines = []
    ) {
        return this._tlGetPriceComputation(
            pricelist,
            quantity,
            price_extra,
            recurring,
            variant,
            original_line,
            related_lines
        ).price;
    },

    getPricelistTripleDiscountValues(
        pricelist,
        quantity,
        price_extra = 0,
        variant = false,
        original_line = false,
        related_lines = []
    ) {
        const result = this._tlGetPriceComputation(
            pricelist,
            quantity,
            price_extra,
            false,
            variant,
            original_line,
            related_lines
        );
        if (!result.exposeDiscounts) {
            return {
                discount: 0,
                discount2: 0,
                discount3: 0,
                discounting_type: "multiplicative",
                hasDiscounts: false,
            };
        }
        const [discount, discount2, discount3] = getRuleDiscounts(result.rule);
        return {
            discount,
            discount2,
            discount3,
            discounting_type: "multiplicative",
            hasDiscounts: true,
        };
    },
});
