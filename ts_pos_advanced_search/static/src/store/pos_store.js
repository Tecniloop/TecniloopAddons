/**@odoo-module **/
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { normalize } from "@web/core/l10n/utils";
import { patch } from "@web/core/utils/patch";
patch(PosStore.prototype, {

    // @override
    getProductsBySearchWord(searchWord, products) {
        const words = normalize(searchWord).toLowerCase();
        const searchWords = words.split(/\s+/).filter(word => word.length >= 1);

        if (!searchWords.length) return [];

        const seen = new Set();
        const exactMatches = [];
        const partialMatches = [];

        for (const product of products) {
            const productText = normalize(product.searchString).toLowerCase();

            const allTexts = [productText];
            const isExact = product.exactMatch?.(words);
            const fullMatch = allTexts.some(t => t.includes(words));
            const splitMatch = searchWords.every(sw =>
                allTexts.some(t => t.includes(sw))
            );

            if (isExact || fullMatch) {
                if (!seen.has(product.id)) {
                    seen.add(product.id);
                    exactMatches.push(product);
                }
            } else if (splitMatch) {
                if (!seen.has(product.id)) {
                    seen.add(product.id);
                    partialMatches.push(product);
                }
            }
        }

        const combined = [...exactMatches, ...partialMatches];

        const scored = combined.map(product => {
            const normName = normalize(product.normalizedName).toLowerCase();
            return {
                product,
                index: normName.indexOf(words),
                name: normName,
            };
        });

        scored.sort(
            (a, b) =>
                (a.index === -1) - (b.index === -1) ||
                a.index - b.index ||
                (a.name === b.name ? 0 : a.name > b.name ? 1 : -1)
        );

        return scored.map(s => s.product);
    },

});
