/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.productBrands = publicWidget.Widget.extend({
  selector: '.oe_website_sale',

  events: {
    'click a.wk_brand': '_onClickWkBrand',
  },

  init() {
    this._super(...arguments);
  },

  _onClickWkBrand: function (ev) {
    var wk_brand = $(ev.currentTarget).data('wk_brand');
    $.each($('.o_products_attributes_brands').find("input[name='attrib_brand']:checked"),
      function () {
        if (wk_brand == $(this).data('wk_brand')) {
          $(this).click();
        }
      });
  },
});

publicWidget.registry.productbrands = publicWidget.Widget.extend({
  selector: '.website_product_brands_carousal',
  disabledInEditableMode: false,

  init() {
    this._super(...arguments);
  },

  start: function () {
    this.setData();
    return this._super.apply(this, arguments);
  },

  setData: function () {
    var self = this;
    self.list = {
      rtl: true,
      margin: 10,
      nav: true,
      loop: true,
      lazyLoad: false,
      smartSpeed: 1000,
      navText: ["<i class='fa fa-caret-right'></i>", "<i class='fa fa-caret-left'></i>"],
      responsive: {
        0: {
          items: 1
        },
        600: {
          items: 3
        },
        1000: {
          items: 5
        }
      }
    };

    rpc('/get/product/brands').then(function (response) {
      self.$target.html(response);
      $('.product_brand_span').removeAttr('data-oe-model data-oe-id data-oe-xpath data-oe-field data-oe-type data-oe-expression');
      self.owl_for_home();
    })
  },

  owl_for_home: function () {
    var $ref = this;
    var $carousal = $ref.$target.find('.owl-carousel');
    if ($carousal.length > 0) {
      var ref = $carousal.find('.carousel-item');
      var con = ref.length > 5;
      $ref.list.loop = con ? true : false;
      $ref.list.rtl = con ? true : false;
      $carousal.owlCarousel($ref.list);
      $ref.setHeight($ref.$target);
      $carousal.on('changed.owl.carousel', function (ev) {
        $ref.setHeight($ref.$target);
      });
      $carousal.on('resized.owl.carousel', function (ev) {
        $ref.setHeight($ref.$target);
      })
    }
  },

  setHeight: function (ele) {
    ele.find('.p-container').each(function () {
      this.style.height = this.offsetWidth;
      var span = $(this).find('span');
      span.height(this.offsetWidth - 2 * (15 + 6 + 8));
      span.find('img').addClass('maxWidth').removeClass('w-100');
    });
  },

  destroy: function () {
    this._clearContent();
    this._super.apply(this, arguments);
  },

  _clearContent: function () {
    const $templateArea = this.$el.find('.carousel-item');
    this.trigger_up('widgets_stop_request', {
      $target: $templateArea,
    });
    $templateArea.html('');
  },
});
