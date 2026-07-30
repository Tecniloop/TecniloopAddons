import { registry } from "@web/core/registry";
import { DynamicSnippetProducts } from "@website_sale/snippets/s_dynamic_snippet_products/dynamic_snippet_products";

/**
 * Dynamic product carousel restricted to the categories of the product page.
 *
 * The standard product dynamic snippet remains untouched. This interaction has
 * its own selector and only reuses Odoo's public DynamicSnippetProducts class.
 */
export class SameCategoryProducts extends DynamicSnippetProducts {
    static selector = ".s_same_category_products";

    /**
     * Replace the standard configurable category domain with the categories
     * assigned to the product currently displayed.
     *
     * @override
     */
    getCategorySearchDomain() {
        const productDetailEl = document.body.querySelector("#product_detail");
        if (!productDetailEl) {
            // This snippet is meaningful only on a product page.
            return [["id", "=", 0]];
        }

        const categoryIds = (productDetailEl.dataset.sameCategoryPublicCategoryIds || "")
            .split(",")
            .map((categoryId) => parseInt(categoryId, 10))
            .filter(Number.isInteger);
        if (!categoryIds.length) {
            return [["id", "=", 0]];
        }

        const domain = [["public_categ_ids", "in", categoryIds]];
        const productTemplateId = parseInt(
            productDetailEl.dataset.sameCategoryProductTemplateId,
            10
        );
        if (Number.isInteger(productTemplateId)) {
            domain.push(["product_tmpl_id", "!=", productTemplateId]);
        }
        return domain;
    }

    /**
     * Keep cross-selling-compatible RPC parameters if an editor changes the
     * underlying dynamic filter, while obtaining the ID from the robust page
     * dataset instead of relying on the add-to-cart form.
     *
     * @override
     */
    getRpcParameters() {
        const parameters = super.getRpcParameters(...arguments);
        const productTemplateId = parseInt(
            document.body.querySelector("#product_detail")?.dataset
                .sameCategoryProductTemplateId,
            10
        );
        if (Number.isInteger(productTemplateId)) {
            parameters.productTemplateId = productTemplateId;
        }
        return parameters;
    }
}

registry
    .category("public.interactions")
    .add("tl_website_sale_same_category_carousel.same_category_products", SameCategoryProducts);

registry
    .category("public.interactions.edit")
    .add("tl_website_sale_same_category_carousel.same_category_products", {
        Interaction: SameCategoryProducts,
    });

registry
    .category("public.interactions.preview")
    .add("tl_website_sale_same_category_carousel.same_category_products", {
        Interaction: SameCategoryProducts,
    });
