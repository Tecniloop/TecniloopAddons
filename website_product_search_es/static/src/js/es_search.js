/** @odoo-module **/

import publicWidget from '@web/legacy/js/public/public_widget';
import { rpc } from '@web/core/network/rpc';

    publicWidget.registry.EsSearch = publicWidget.Widget.extend({
        selector: '.js_sale',

        start: function () {
            this._boundInput = this._onInput.bind(this);
            this._boundFocus = this._onFocus.bind(this);
            this._boundKeydown = this._onKeydown.bind(this);
            this._boundSearchEvent = this._onSearchEvent.bind(this);
            this._boundSubmit = this._onSubmit.bind(this);
            this._boundFilterChange = this._onFilterChange.bind(this);
            this._boundDocClick = this._onDocClick.bind(this);

            this._activeIndex = -1;
            this._itemsCache = [];
            this._searchTimer = null;
            this.$activeInput = null;

            $(document).on('input', '.o_wsale_products_searchbar_form input[name="search"]', this._boundInput);
            $(document).on('focus', '.o_wsale_products_searchbar_form input[name="search"]', this._boundFocus);
            $(document).on('keydown', '.o_wsale_products_searchbar_form input[name="search"]', this._boundKeydown);
            $(document).on('search', '.o_wsale_products_searchbar_form input[name="search"]', this._boundSearchEvent);
            $(document).on('submit', '.o_wsale_products_searchbar_form', this._boundSubmit);
            $(document).on('change', '#es-min-price, #es-max-price, #es-attrs, #es-brand', this._boundFilterChange);
            $(document).on('click', this._boundDocClick);
            this._syncFiltersFromUrl();

            return this._super.apply(this, arguments);
        },

        destroy: function () {
            $(document).off('input', '.o_wsale_products_searchbar_form input[name="search"]', this._boundInput);
            $(document).off('focus', '.o_wsale_products_searchbar_form input[name="search"]', this._boundFocus);
            $(document).off('keydown', '.o_wsale_products_searchbar_form input[name="search"]', this._boundKeydown);
            $(document).off('search', '.o_wsale_products_searchbar_form input[name="search"]', this._boundSearchEvent);
            $(document).off('submit', '.o_wsale_products_searchbar_form', this._boundSubmit);
            $(document).off('change', '#es-min-price, #es-max-price, #es-attrs, #es-brand', this._boundFilterChange);
            $(document).off('click', this._boundDocClick);
            if (this._searchTimer) {
                clearTimeout(this._searchTimer);
            }
            return this._super.apply(this, arguments);
        },

        _escapeHtml: function (s) {
            return String(s || '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        },

        _formatPrice: function (p) {
            if (p === undefined || p === null || p === '') {
                return '';
            }
            const num = Number(p);
            if (Number.isNaN(num)) {
                return '';
            }
            return num.toFixed(2);
        },

        _renderBadges: function (badges, limit) {
            if (!badges || !badges.length) {
                return '';
            }
            let badgeList = badges;
            if (limit && Number.isInteger(limit) && limit > 0) {
                badgeList = badges.slice(0, limit);
            }
            const clsFor = (badge) => {
                const v = String(badge || '').toLowerCase();
                if (v.includes('best')) {
                    return 'es-badge-bestseller';
                }
                if (v.includes('trend')) {
                    return 'es-badge-trending';
                }
                if (v.includes('new')) {
                    return 'es-badge-new';
                }
                return 'es-badge-default';
            };
            const items = badgeList.map((b) => `<span class="es-badge-chip ${clsFor(b)}">${this._escapeHtml(b)}</span>`);
            return `<div class="es-badges">${items.join('')}</div>`;
        },

        _onDocClick: function (ev) {
            const $box = this._getSuggestBox();
            if (!$box.length) {
                return;
            }
            if ($(ev.target).closest('.es-search-suggestions, .o_wsale_products_searchbar_form').length) {
                return;
            }
            $box.hide();
            this._activeIndex = -1;
        },

        _onKeydown: function (ev) {
            const $box = this._getSuggestBox();
            if (!$box.is(':visible') || !this._itemsCache.length) {
                return;
            }
            if (ev.key === 'ArrowDown') {
                ev.preventDefault();
                this._activeIndex = (this._activeIndex + 1) % this._itemsCache.length;
                this._paintActiveItem();
            } else if (ev.key === 'ArrowUp') {
                ev.preventDefault();
                this._activeIndex = this._activeIndex <= 0 ? this._itemsCache.length - 1 : this._activeIndex - 1;
                this._paintActiveItem();
            } else if (ev.key === 'Enter') {
                if (this._activeIndex >= 0 && this._itemsCache[this._activeIndex]) {
                    ev.preventDefault();
                    window.location.href = this._itemsCache[this._activeIndex].url;
                }
            } else if (ev.key === 'Escape') {
                $box.hide();
                this._activeIndex = -1;
            }
        },

        _paintActiveItem: function () {
            const $box = this._getSuggestBox();
            $box.find('.es-item-link').removeClass('active');
            if (this._activeIndex >= 0) {
                $box.find(`.es-item-link[data-index="${this._activeIndex}"]`).addClass('active');
            }
        },

        _onSubmit: function (ev) {
            if (!$(ev.currentTarget).find('input[name="search"]').length) {
                return;
            }
            ev.preventDefault();
            this._fetchSearchResults();
        },

        _onFilterChange: function () {
            this._fetchSearchResults();
        },

        _onFocus: function (ev) {
            this.$activeInput = $(ev.currentTarget);
            this._requestSuggest($(ev.currentTarget).val() || '');
        },

        _onInput: function (ev) {
            this.$activeInput = $(ev.currentTarget);
            const query = $(ev.currentTarget).val() || '';
            if (this._searchTimer) {
                clearTimeout(this._searchTimer);
            }
            this._searchTimer = setTimeout(() => this._requestSuggest(query), 220);
        },

        _onSearchEvent: function (ev) {
            const query = ($(ev.currentTarget).val() || '').trim();
            if (!query) {
                this._fetchSearchResults({ forceClearSearch: true });
            }
        },

        _syncFiltersFromUrl: function () {
            const params = new URLSearchParams(window.location.search);
            const setIfPresent = (selector, key) => {
                const value = params.get(key);
                if (value !== null) {
                    $(selector).val(value);
                }
            };
            setIfPresent('#es-min-price', 'min_price');
            setIfPresent('#es-max-price', 'max_price');
            setIfPresent('#es-attrs', 'attrs');
            setIfPresent('#es-brand', 'brand');
        },

        _requestSuggest: function (query) {
            const $box = this._getSuggestBox();
            $box.html('<div class="es-loading">Loading...</div>').show();
            $.get('/es/search_suggest', { q: query }).then((data) => {
                this._renderSuggest(query, data || {});
            }).catch(() => {
                $box.hide();
            });
        },

        _getSuggestBox: function () {
            if (this.$activeInput && this.$activeInput.length) {
                const $formBox = this.$activeInput.closest('form').find('.es-search-suggestions').first();
                if ($formBox.length) {
                    return $formBox;
                }
            }
            return $('.es-search-suggestions').first();
        },

        _trackSuggestionClick: function (query, productId, source) {
            if (!productId) {
                return Promise.resolve();
            }
            return rpc('/es/search_click', {
                query: query || '',
                product_id: productId,
                source: source || 'suggestion',
            }).catch(() => {});
        },

        _renderSuggest: function (query, data) {
            const $box = this._getSuggestBox();
            if (data && data.autocomplete_enabled === false) {
                $box.hide().empty();
                this._itemsCache = [];
                this._activeIndex = -1;
                return;
            }
            const rows = [];
            const items = [];

            const appendProducts = (title, list, source) => {
                if (!list || !list.length) {
                    return;
                }
                rows.push(`<div class="es-heading">${this._escapeHtml(title)}</div>`);
                list.forEach((p) => {
                    const idx = items.length;
                    items.push({ url: p.url || '#' });
                    const category = p.category ? `<div class="es-item-category">${this._escapeHtml(p.category)}</div>` : '';
                    const image = p.image_url
                        ? `<img class="es-item-image" src="${p.image_url}" alt="${this._escapeHtml(p.name || '')}" loading="lazy"/>`
                        : '<div class="es-item-image es-item-image-empty"></div>';
                    const priceText = (p.price_label || p.detail || this._formatPrice(p.price) || '').trim();
                    const badgesHtml = this._renderBadges(p.badges || [], 2);
                    rows.push(
                        `<a class="es-item-link dropdown-item p-2 text-wrap" data-index="${idx}" data-product-id="${Number(p.id || 0)}" data-source="${this._escapeHtml(source)}" data-query="${this._escapeHtml(query)}" href="${p.url || '#'}">
                            <span class="es-item-left flex-shrink-0">${image}</span>
                            <span class="es-item-main px-2">
                                <span class="es-item-name h6 fw-bold mb-0">${this._escapeHtml(p.name || '')}</span>
                                ${category}
                                ${badgesHtml}
                            </span>
                            <span class="es-item-price">${this._escapeHtml(priceText)}</span>
                        </a>`
                    );
                });
            };

            appendProducts('Suggestions', data.results || [], 'suggestion');
            appendProducts('Trending Products', data.trending_products || [], 'trending_product');

            if (data.trending && data.trending.length) {
                rows.push('<div class="es-heading">Trending Searches</div>');
                data.trending.forEach((term) => {
                    const termSafe = this._escapeHtml(term);
                    rows.push(`<button type="button" class="es-term-btn" data-term="${termSafe}">${termSafe}</button>`);
                });
            }

            if (!rows.length) {
                $box.html('<div class="es-empty">No suggestions</div>').show();
                this._itemsCache = [];
                this._activeIndex = -1;
                return;
            }

            $box.html(rows.join('')).show();
            this._itemsCache = items;
            this._activeIndex = -1;

            $box.find('.es-item-link').on('click', (ev) => {
                const $el = $(ev.currentTarget);
                const href = $el.attr('href') || '#';
                const productId = parseInt($el.data('productId') || 0, 10);
                const source = String($el.data('source') || 'suggestion');
                const clickQuery = String($el.data('query') || query || '');
                if (!productId || !href || href === '#') {
                    return;
                }
                ev.preventDefault();
                let navigated = false;
                const go = () => {
                    if (navigated) {
                        return;
                    }
                    navigated = true;
                    window.location.href = href;
                };
                const timer = setTimeout(go, 160);
                this._trackSuggestionClick(clickQuery, productId, source).then(() => {
                    clearTimeout(timer);
                    go();
                });
            });

            $box.find('.es-term-btn').on('click', (ev) => {
                const term = $(ev.currentTarget).data('term') || '';
                $('.o_wsale_products_searchbar_form input[name="search"]').first().val(term);
                this._fetchSearchResults();
            });
        },

        _fetchSearchResults: function (options) {
            const opts = options || {};
            const currentParams = new URLSearchParams(window.location.search);
            const currentPath = window.location.pathname || '/shop';
            const inputQuery = $('.o_wsale_products_searchbar_form input[name="search"]').first().val() || '';
            const query = opts.forceClearSearch ? inputQuery : (inputQuery || currentParams.get('search') || '');
            const minPrice = $('#es-min-price').val() || '';
            const maxPrice = $('#es-max-price').val() || '';
            const attrs = $('#es-attrs').val() || '';
            const brand = $('#es-brand').val() || '';
            const categoryId = currentParams.get('category') || '';
            const params = new URLSearchParams(currentParams.toString());
            params.delete('page');
            if (query) {
                params.set('search', query);
            } else {
                params.delete('search');
            }
            if (categoryId) {
                params.set('category', categoryId);
            }
            if (minPrice) {
                params.set('min_price', minPrice);
            } else {
                params.delete('min_price');
            }
            if (maxPrice) {
                params.set('max_price', maxPrice);
            } else {
                params.delete('max_price');
            }
            if (attrs) {
                params.set('attrs', attrs);
            } else {
                params.delete('attrs');
            }
            if (brand) {
                params.set('brand', brand);
            } else {
                params.delete('brand');
            }
            $('.es-search-suggestions').hide();
            const queryString = params.toString();
            const basePath = currentPath.indexOf('/shop/category/') === 0 ? currentPath : '/shop';
            window.location.href = queryString ? `${basePath}?${queryString}` : basePath;
        },

        _renderResults: function (results) {
            const $container = $('.o_wsale_products_grid_table_wrapper');
            if (!$container.length) {
                return;
            }
            if (!results.length) {
                $container.html('<div class="text-center text-muted py-5">No results found.</div>');
                return;
            }

            const items = results.map((r) => (
                `<div class="es-product-card">
                    <a href="${r.url}" class="es-product-name">${this._escapeHtml(r.name || '')}</a>
                    ${this._renderBadges(r.badges || [], 2)}
                    <div class="es-product-price">${this._escapeHtml(r.price_label || this._formatPrice(r.price))}</div>
                </div>`
            ));
            $container.html(`<div class="es-product-grid">${items.join('')}</div>`);
        },

        _renderFacets: function (facets) {
            const $facets = $('#es-facets');
            if (!$facets.length) {
                return;
            }
            const sections = [];
            if (facets.categories && facets.categories.length) {
                const cats = facets.categories.map((c) => `<span class="badge bg-light text-dark me-1">${this._escapeHtml(c.key)} (${c.doc_count})</span>`);
                sections.push(`<div class="es-facet-group"><strong>Categories:</strong> ${cats.join('')}</div>`);
            }
            if (facets.brands && facets.brands.length) {
                const brands = facets.brands.map((b) => `<span class="badge bg-light text-dark me-1">${this._escapeHtml(b.key)} (${b.doc_count})</span>`);
                sections.push(`<div class="es-facet-group"><strong>Brands:</strong> ${brands.join('')}</div>`);
            }
            if (facets.attributes && facets.attributes.length) {
                const attrs = facets.attributes.map((a) => `<span class="badge bg-light text-dark me-1">${this._escapeHtml(a.key)} (${a.doc_count})</span>`);
                sections.push(`<div class="es-facet-group"><strong>Attributes:</strong> ${attrs.join('')}</div>`);
            }
            $facets.html(sections.join(''));
        },
    });
