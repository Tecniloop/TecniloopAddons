/** @odoo-module **/

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { session } from "@web/session";
import { patch } from "@web/core/utils/patch";

patch(ProductScreen.prototype, {
        async addProductToOrder(product, options = {}) {
            var self = this;
            if(this.pos.config.display_discount_price && product.discount_price > 0){
                    var discount_price = product.discount_price
                    product.list_price = discount_price;
                     this.pos.addLineToCurrentOrder({ product_tmpl_id: product, price_unit: discount_price });
            }else{
                 super.addProductToOrder(...arguments);
            }
        }
});

