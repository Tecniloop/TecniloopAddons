import json
import logging
import re
from urllib.parse import urljoin, urlparse, urlunparse

from lxml import etree
from lxml import html as lxml_html

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class BlogPost(models.Model):
    _inherit = 'blog.post'

    sitemap_source_id = fields.Many2one(
        'sitemap.import.source', string='Fuente de importación', copy=False,
        readonly=True, index=True,
    )
    sitemap_source_url = fields.Char(
        string='URL original del artículo', copy=False, readonly=True, index=True,
    )
    sitemap_last_sync = fields.Datetime(
        string='Última sincronización', copy=False, readonly=True,
    )
    sitemap_product_tmpl_ids = fields.Many2many(
        'product.template', 'sitemap_blog_post_product_rel',
        'blog_post_id', 'product_tmpl_id', string='Productos relacionados',
        readonly=True, copy=False,
    )

    _sitemap_blog_source_url_uniq = models.Constraint(
        'unique(sitemap_source_url)',
        message='Ya existe un artículo importado con esta URL original.',
    )


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    sitemap_blog_post_ids = fields.Many2many(
        'blog.post', 'sitemap_blog_post_product_rel',
        'product_tmpl_id', 'blog_post_id', string='Recetas y artículos relacionados',
        readonly=True, copy=False,
    )

    @api.model
    def _sitemap_blog_find_or_create_blog(self, source):
        Blog = self.env['blog.blog']
        website_id = getattr(source, 'website_id', False)
        domain = [('name', '=', 'Recetas')]
        if website_id and 'website_id' in Blog._fields:
            domain.append(('website_id', '=', website_id.id))
        blog = Blog.search(domain, limit=1)
        if blog:
            return blog
        vals = {'name': 'Recetas'}
        if website_id and 'website_id' in Blog._fields:
            vals['website_id'] = website_id.id
        return Blog.create(vals)

    @staticmethod
    def _sitemap_blog_inner_html(node):
        parts = []
        if node.text:
            parts.append(node.text)
        for child in node:
            parts.append(etree.tostring(child, encoding='unicode', method='html'))
        return ''.join(parts).strip()

    @api.model
    def _sitemap_blog_fetch_article(self, connector, source, article):
        url = str((article or {}).get('url') or '').strip()
        if not url:
            return {}
        session = connector._get_session(source)
        response = connector._http_get(session, url, source)
        tree = lxml_html.fromstring(response.content)

        def first_text(xpaths):
            for xpath in xpaths:
                nodes = tree.xpath(xpath)
                if nodes:
                    node = nodes[0]
                    if isinstance(node, str):
                        value = connector._clean_text(node)
                    else:
                        value = connector._clean_text(' '.join(node.itertext()))
                    if value:
                        return value
            return ''

        title = first_text((
            '//main//h1[normalize-space()]',
            '//article//h1[normalize-space()]',
            '//h1[normalize-space()]',
            '//meta[@property="og:title"]/@content',
        ))

        content = ''
        content_xpaths = (
            '//main//article//*[contains(concat(" ", normalize-space(@class), " "), " article-template__content ")]',
            '//article//*[contains(concat(" ", normalize-space(@class), " "), " rte ")]',
            '//main//*[contains(concat(" ", normalize-space(@class), " "), " article-content ")]',
            '//main//article',
        )
        for xpath in content_xpaths:
            nodes = tree.xpath(xpath)
            for node in nodes:
                plain = connector._clean_text(' '.join(node.itertext()))
                if len(plain) < 80:
                    continue
                content = self._sitemap_blog_inner_html(node)
                if content:
                    break
            if content:
                break

        meta_title = first_text(('//meta[@property="og:title"]/@content', '//title/text()'))
        meta_description = first_text((
            '//meta[@name="description"]/@content',
            '//meta[@property="og:description"]/@content',
        ))
        image_url = first_text((
            '//meta[@property="og:image:secure_url"]/@content',
            '//meta[@property="og:image"]/@content',
            '//article//img[1]/@src',
        ))
        if image_url:
            image_url = urljoin(response.url, image_url)

        canonical = first_text(('//link[@rel="canonical"]/@href',)) or response.url
        parsed = urlparse(canonical)
        canonical = urlunparse(parsed._replace(query='', fragment=''))
        return {
            'url': canonical,
            'name': title,
            'content': content,
            'meta_title': meta_title,
            'meta_description': meta_description,
            'image_url': image_url,
        }

    def _sitemap_sync_blog_articles(self, connector, source, articles, public_html):
        self.ensure_one()
        BlogPost = self.env['blog.post']
        blog = self._sitemap_blog_find_or_create_blog(source)
        posts = BlogPost
        replacements = {}

        unique = {}
        for item in articles or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get('url') or '').strip()
            if url:
                unique[url.split('#', 1)[0]] = item

        for original_url, item in unique.items():
            try:
                payload = self._sitemap_blog_fetch_article(connector, source, item)
            except Exception as exc:  # noqa: BLE001 - article is supplementary
                _logger.warning(
                    'Sitemap import: no se pudo importar el artículo %s: %s',
                    original_url, exc,
                )
                continue
            source_url = payload.get('url') or original_url
            post = BlogPost.search([('sitemap_source_url', 'in', [source_url, original_url])], limit=1)
            vals = {
                'name': payload.get('name') or item.get('name') or source_url,
                'content': payload.get('content') or '',
                'blog_id': blog.id,
                'sitemap_source_id': source.id,
                'sitemap_source_url': source_url,
                'sitemap_last_sync': fields.Datetime.now(),
            }
            if 'website_published' in BlogPost._fields:
                vals['website_published'] = True
            if 'website_meta_title' in BlogPost._fields and payload.get('meta_title'):
                vals['website_meta_title'] = payload['meta_title']
            if 'website_meta_description' in BlogPost._fields and payload.get('meta_description'):
                vals['website_meta_description'] = payload['meta_description']
            if 'cover_properties' in BlogPost._fields and payload.get('image_url'):
                vals['cover_properties'] = json.dumps({
                    'background-image': 'url(%s)' % payload['image_url'],
                    'resize_class': 'o_record_has_cover o_half_screen_height',
                    'opacity': '0',
                })
            if post:
                post.write(vals)
            else:
                post = BlogPost.create(vals)
            posts |= post
            target = getattr(post, 'website_url', False)
            if target:
                replacements[original_url] = target
                replacements[source_url] = target

        previous = self.sitemap_blog_post_ids
        self.sitemap_blog_post_ids = [(6, 0, posts.ids)]

        html_value = public_html or ''
        if html_value and replacements:
            tree = lxml_html.fragment_fromstring(html_value, create_parent='div')
            for link in tree.xpath('.//a[@href]'):
                href = link.get('href') or ''
                absolute = urljoin(self.sitemap_source_url or '', href).split('#', 1)[0]
                target = replacements.get(absolute)
                if target:
                    fragment = urlparse(href).fragment
                    link.set('href', target + (('#' + fragment) if fragment else ''))
            rewritten = self._sitemap_blog_inner_html(tree)
            self.write(self._sitemap_description_cleanup_vals(rewritten))

        # The M2M assignment removes obsolete product/article links without
        # deleting the shared blog posts themselves.
        return posts, previous - posts
