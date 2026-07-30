/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.ShProductSocialSharingToggle = publicWidget.Widget.extend({
    selector: ".js_cls_sh_product_social_sharing_wrapper",
    events: {
        "click #js_id_sh_prod_social_sharing_show_more_a": "_onShowMore",
        "click #js_id_sh_prod_social_sharing_show_less_a": "_onShowLess",
    },

    start() {
        this._items = this.$("#js_id_sh_prod_social_sharing_main_ul > li, #js_id_sh_prod_social_sharing_main_div > a");
        this._visibleItemCount = 4;
        this._updateItems(false);
        return this._super.apply(this, arguments);
    },

    _updateItems(showAll) {
        if (!this._items.length) {
            return;
        }
        this._items.toggle(showAll);
        if (!showAll) {
            this._items.slice(0, this._visibleItemCount).show();
        }
        const hasHiddenItems = this._items.length > this._visibleItemCount;
        this.$("#js_id_sh_prod_social_sharing_show_more_a").toggle(hasHiddenItems && !showAll);
        this.$("#js_id_sh_prod_social_sharing_show_less_a").toggle(hasHiddenItems && showAll);
    },

    _onShowMore(event) {
        event.preventDefault();
        this._updateItems(true);
    },

    _onShowLess(event) {
        event.preventDefault();
        this._updateItems(false);
    },
});
