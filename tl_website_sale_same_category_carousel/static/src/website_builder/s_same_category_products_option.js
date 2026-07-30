import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { registry } from "@web/core/registry";
import { DYNAMIC_SNIPPET_CAROUSEL } from "@website/builder/plugins/options/dynamic_snippet_carousel_option_plugin";
import {
    DynamicSnippetProductsOption,
    getContextualFilterDomain,
} from "@website_sale/website_builder/dynamic_snippet_products_option";

class SameCategoryProductsOption extends DynamicSnippetProductsOption {
    static selector = ".s_same_category_products";
    static template =
        "tl_website_sale_same_category_carousel.SameCategoryProductsOption";

    setup() {
        super.setup();
        // The data source is intentionally fixed; only presentation options remain.
        this.dynamicOptionParams.showFilterOption = () => false;
    }
}

class SameCategoryProductsOptionPlugin extends Plugin {
    static id = "sameCategoryProductsOption";
    static dependencies = ["dynamicSnippetCarouselOption"];

    resources = {
        builder_options: withSequence(
            DYNAMIC_SNIPPET_CAROUSEL,
            SameCategoryProductsOption
        ),
        dynamic_snippet_template_updated: this.onTemplateUpdated.bind(this),
        on_snippet_dropped_handlers: this.onSnippetDropped.bind(this),
    };

    async onSnippetDropped({ snippetEl }) {
        if (!snippetEl.matches(SameCategoryProductsOption.selector)) {
            return;
        }
        await this.dependencies.dynamicSnippetCarouselOption.setOptionsDefaultValues(
            snippetEl,
            "product.product",
            getContextualFilterDomain(this.editable)
        );
    }

    onTemplateUpdated({ el, template }) {
        if (el.matches(SameCategoryProductsOption.selector)) {
            this.dependencies.dynamicSnippetCarouselOption.updateTemplateSnippetCarousel(
                el,
                template
            );
        }
    }
}

registry
    .category("website-plugins")
    .add(SameCategoryProductsOptionPlugin.id, SameCategoryProductsOptionPlugin);
