/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.ShProductSocialSharingWebsiteLinks = publicWidget.Widget.extend({
    selector: ".js_cls_sh_product_social_sharing_wrapper",
    events: {
        "click ul.links li a.link": "_onClickSocialShareLink",
        "click div.links div.col div a.link": "_onClickSocialShareLink",
        "click div.row.links a.link": "_onClickSocialShareLink",
        "click .share_icons a.link": "_onClickSocialShareLink",
    },

    _onClickSocialShareLink(event) {
        event.preventDefault();
        const link = event.currentTarget;
        const shareUrl = link.getAttribute("data_social_href");
        if (!shareUrl) {
            return;
        }
        window.location.href = shareUrl + encodeURIComponent(window.location.href);
    },
});
