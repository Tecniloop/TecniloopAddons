/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import VariantMixin from "@website_sale/js/sale_variant_mixin";
import { rpc } from "@web/core/network/rpc";
import "@website_sale/js/website_sale";
import wSaleUtils from "@website_sale/js/website_sale_utils";
import { Component } from "@odoo/owl";

publicWidget.registry.WebsiteSale.include({
    events: Object.assign({}, publicWidget.registry.WebsiteSale.prototype.events, {
        "click .js_matrix_input": "onChangeVariant",
        "change .js_matrix_input": "onChangeVariant",
        "change .js_matrix_input": "_onChangeCartQuantity",
        "click .js_open_product_matrix": "openProductMatrix",
        "change .o_wsale_apply_layout input": "changeLayoutMode",
        "click .variant_custom_button": "addDescription",
    }),

    init: function () {
        this._super.apply(this, arguments);
        this.rpc = rpc;
        // Get Product Quantities
        if (!window.location.pathname.includes('/cart') &&
            !window.location.pathname.includes('/address') &&
            !window.location.pathname.includes('/payment') &&
            !window.location.pathname.includes('/checkout')) {

            var product_ids = [];
            $("[data-product-id]").each(function() {
                product_ids.push($(this).data('product-id'));
            });
            if (product_ids) {
                this.rpc("/website_sale_b2b/get_product_quantities", {
                    product_ids: product_ids,
                }).then(res => {
                    // Set Product Quantities
                    if (res) {
                        res.forEach((product) => $(`[data-product-id=${product['product_id']}]`).val(product['qty']));
                    }
                });
            }
        }
    },

    changeLayoutMode: function (ev) {
        var clickedValue = $(ev.target).val();
        var isList = clickedValue === 'list';
        if (isList) {
            // Show list view
            $(".o_list_view").each(function() {
                $(this).addClass('d-lg-block');
            });
            // Hide kanban view
            $(".o_kanban_view").each(function() {
                $(this).addClass('d-lg-none');
            });
            // Show opened tables
            $(".web_matrix").each(function() {
                $(this).show();
                $(this).parent().parent().find('.o_list_view').removeClass('d-lg-block');
            });

        } else {
            // Hide list view
            $(".o_list_view").each(function() {
                $(this).removeClass('d-lg-block');
            });
            // Show kanban view
            $(".o_kanban_view").each(function() {
                $(this).removeClass('d-lg-none');
            });
            // Hide opened tables
            $(".web_matrix").each(function() {
                $(this).hide();
            });
        }
    },

    addDescription: function (ev) {
        var product_id = $('.js_matrix_input.btn-primary').data('product-id');
        var value = $('.variant_custom_value').val();
        console.log('entra');
        this.rpc("/website_sale_b2b/add_description", {
            product_id: product_id,
            value: value,
        }).then(function (res) {
             window.alert(res);
        });
    },

    onChangeVariant: function (ev) {
        var target = $(ev.currentTarget);
        var parent = $(target).parent();
        if ($(parent).hasClass('js_matrix_inputs')) {
            if ($(target).hasClass('js_matrix_input')) {
                // Remove all selected color
                $('.js_matrix_input').removeClass('btn-primary');
                // Set selected color
                target.addClass('btn-primary');

                var inputs = $(parent).find('.o_attribute_inputs').find('input');
                // Remove all checked attributes
                $('.js_variant_change:checked').removeAttr("checked");
                // Add checked attributes
                $(inputs).each(function() {
                    $(this).attr("checked", "checked");
                });
                // Set qty to add
                $(parent).find("input[name='add_qty']").val($(target).val());

                // Show custom field
                $('.variant_custom_value').remove();
                $('.variant_custom_button').remove();
                if ($(target).data('is_custom') === 'True') {
                    // Input
                    var attributeValueId = $(target).data('value_id');
                    var attributeValueName = $(target).data('value_name');
                    var $input = $('<input>', {
                        type: 'text',
                        'data-custom_product_template_attribute_value_id': attributeValueId,
                        'data-attribute_value_name': attributeValueName,
                        class: 'variant_custom_value form-control mt-2'
                    });
                    $input.attr('placeholder', attributeValueName);
                    $input.addClass('custom_value_radio');
                    $('.col_custom_input').append($input);

                    // Button
                    $('.col_custom_button').append(`
                        <a class='variant_custom_button btn btn-warning float-end mt-2' role='button'>
                            <span>Add description</span>
                        </a>
                    `);
                }

                return VariantMixin.onChangeVariant.apply(this, arguments);
            }
        } else {
            return VariantMixin.onChangeVariant.apply(this, arguments);
        }
    },

    openProductMatrix: function (ev) {
        var self = this;
        var target = $(ev.currentTarget);

        this.rpc("/website_sale_b2b/show_product_matrix_website", {
                product_id: $(target).data('product-id'),
            }).then((modalContent) => {
            if (modalContent) {
                var selector = $(target).closest(".oe_product_cart");
                $(target).removeClass('d-lg-block');
                $(selector).append($(modalContent));
            }
        });
    },

    _updateProductImage: function ($productContainer, displayImage, productId, productTemplateId) {
        // Execute it just in product page
        if ($(this.target).attr('id') == 'product_detail') {
            this._super.apply(this, arguments);
        }
    },

    _applyHashFromSearch() {
        // It was done because a problem when is showed the grid view meanwhile is selected an attribute
        const attributeSelection = this.el.querySelector('.js_add_cart_variants');
        if (!attributeSelection || attributeSelection.dataset.attribute_exclusions != "{'exclusions: []'}") {
            this._super.apply(this, arguments);
        }
    },

    _cartUpdateJson: function ($input, line_id, productId, value) {
        this.rpc("/shop/cart/update_json", {
            line_id: line_id,
            product_id: productId,
            set_qty: value
        }).then(function (data) {
            $input.data('update_change', false);
            var check_value = parseInt($input.val() || 0, 10);
            if (isNaN(check_value)) {
                check_value = 1;
            }
            if (value !== check_value) {
                $input.trigger('change');
                return;
            }
            sessionStorage.setItem('website_sale_cart_quantity', data.cart_quantity);
            if (!data.cart_quantity && window.location.href.includes('/shop/cart')) {
                return window.location = '/shop/cart';
            }
            $input.val(data.quantity);
            $('.js_quantity[data-line-id='+line_id+']').val(data.quantity).text(data.quantity);

            wSaleUtils.updateCartNavBar(data);
            wSaleUtils.showWarning(data.warning);
            // Propagating the change to the express checkout forms
            Component.env.bus.trigger('cart_amount_changed', [data.amount, data.minor_amount]);

            // Enable all buttons
            $('.btn').not(".js_add_cart_json").each(function() {
                $(this).removeClass('disabled');
            });
        });
    },

    _changeCartQuantity: function ($input, value, $dom_optional, line_id, productIDs) {
        var self = this;
        var $input = $input;

        $($dom_optional).toArray().forEach((elem) => {
            $(elem).find('.js_quantity').text(value);
            productIDs.push($(elem).find('span[data-product-id]').data('product-id'));
        });
        $input.data('update_change', true);

        var productId = parseInt($input.data('product-id'), 10);
        var productTemplateId = parseInt($input.data('product-tmpl-id'), 10);
        var productTemplateAttributeValueIds = $input.data('ptav-ids');

        if (isNaN(productId)) {
            var params = {
                product_template_id: productTemplateId,
                product_template_attribute_value_ids:
                    JSON.stringify(productTemplateAttributeValueIds),
            };

            this.rpc('/sale/create_product_variant', params).then(function (productId) {
                self._cartUpdateJson($input, line_id, productId, value);
            });
        } else {
            self._cartUpdateJson($input, line_id, productId, value);
        }
    },

    _onChangeCartQuantity: function (ev) {
        // Disable all buttons
        $('.btn').not(".js_add_cart_json").each(function() {
            $(this).addClass('disabled');
        });
        this._super.apply(this, arguments);
    },
});