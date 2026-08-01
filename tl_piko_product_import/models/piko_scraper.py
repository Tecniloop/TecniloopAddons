# Copyright Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import json
import logging
import re
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    from lxml import etree, html as lxml_html
except ImportError:  # pragma: no cover
    etree = lxml_html = None

# -(\d+).html  -> id externo del artículo/categoría en piko-shop.de
RE_URL_ID = re.compile(r"-(\d+)\.html?$", re.I)
# index.php?vw_type=artikel&vw_id=30320&vw_name=detail (URLs legacy)
RE_LEGACY_ID = re.compile(r"vw_id=(\d+)", re.I)
RE_EAN = re.compile(r"\b(\d{8}|\d{12,14})\b")
RE_SKU_LABEL = re.compile(
    r"(?:artikelnummer|artikel-nr\.?|art\.?\s*nr\.?|item\s*number|sku)\s*[:.]?\s*"
    r"([A-Za-z0-9][A-Za-z0-9._/\-]{2,30})",
    re.I,
)


class TlPikoScraper(models.AbstractModel):
    """Servicio de scraping reutilizable.

    No guarda estado: recibe siempre el `source` (tl.piko.source) del que toma
    configuración (delay, timeout, selectores, robots...). Aislar aquí toda la
    lógica HTTP/HTML permite añadir otras tiendas creando solo métodos
    `_parse_product_<slug>` sin tocar los modelos.
    """

    _name = "tl.piko.scraper"
    _description = "PIKO / Web Scraping Service"

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    @api.model
    def _check_libs(self):
        if requests is None or lxml_html is None:
            raise UserError(
                _("Faltan dependencias Python: se requieren 'requests' y 'lxml'.")
            )

    @api.model
    def _session(self, source):
        self._check_libs()
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": source.user_agent
                or "Mozilla/5.0 (compatible; TecniloopOdooBot/1.0)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "%s,de;q=0.8,en;q=0.7" % (source.lang_code or "de"),
            }
        )
        return session

    @api.model
    def _robots_allows(self, source, url):
        if not source.respect_robots:
            return True
        parsed = urlparse(url)
        root = "%s://%s" % (parsed.scheme, parsed.netloc)
        cache = self.env.registry._tl_piko_robots = getattr(
            self.env.registry, "_tl_piko_robots", {}
        )
        rp = cache.get(root)
        if rp is None:
            rp = RobotFileParser()
            rp.set_url(urljoin(root, "/robots.txt"))
            try:
                rp.read()
            except Exception as exc:  # noqa: BLE001
                _logger.info("robots.txt no accesible en %s: %s", root, exc)
                rp = False
            cache[root] = rp
        if not rp:
            return True
        return rp.can_fetch(source.user_agent or "*", url)

    @api.model
    def _prepare_url(self, source, url):
        """Añade los parámetros fijos de la fuente (p.ej. lang=en)."""
        if not source.extra_params:
            return url
        parts = urlparse(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update(dict(parse_qsl(source.extra_params.lstrip("?"),
                                    keep_blank_values=True)))
        return urlunparse(parts._replace(query=urlencode(query)))

    @api.model
    def http_get(self, source, url):
        """Devuelve el texto de `url` respetando robots, delay y reintentos."""
        url = self._prepare_url(source, url)
        if not self._robots_allows(source, url):
            raise UserError(_("robots.txt no permite acceder a %s") % url)
        session = source._get_session()
        last_error = None
        for attempt in range(max(1, source.max_retries)):
            if source.request_delay:
                time.sleep(source.request_delay)
            try:
                resp = session.get(url, timeout=source.timeout or 30)
                if resp.status_code == 404:
                    return None
                if resp.status_code in (429, 503):
                    time.sleep((attempt + 1) * (source.request_delay or 1) * 5)
                    last_error = "HTTP %s" % resp.status_code
                    continue
                resp.raise_for_status()
                resp.encoding = resp.encoding or "utf-8"
                return resp.text
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                _logger.warning("GET %s falló (intento %s): %s", url, attempt + 1, exc)
        raise UserError(_("No se pudo descargar %(url)s: %(err)s", url=url, err=last_error))

    @api.model
    def http_get_binary(self, source, url):
        url = self._prepare_url(source, url)
        if not self._robots_allows(source, url):
            return None
        session = source._get_session()
        try:
            if source.request_delay:
                time.sleep(source.request_delay)
            resp = session.get(url, timeout=source.timeout or 30)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:  # noqa: BLE001
            _logger.warning("No se pudo descargar la imagen %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------
    # Descubrimiento de URLs de producto
    # ------------------------------------------------------------------
    @api.model
    def discover(self, source, limit=None):
        """Devuelve una lista de URLs de ficha de producto."""
        urls = []
        if source.discovery_mode == "manual":
            urls = [u.strip() for u in (source.url_list or "").splitlines() if u.strip()]
        elif source.discovery_mode == "sitemap":
            urls = self._discover_sitemap(source)
        else:
            urls = self._discover_categories(source)
        seen, result = set(), []
        for url in urls:
            url = urljoin(source.base_url, url).split("#")[0]
            if url in seen or not self._is_product_url(source, url):
                continue
            seen.add(url)
            result.append(url)
            if limit and len(result) >= limit:
                break
        return result

    @api.model
    def _is_product_url(self, source, url):
        pattern = source.product_url_regex or r"/artikel/"
        return bool(re.search(pattern, url, re.I))

    @api.model
    def _discover_sitemap(self, source, url=None, depth=0):
        """Recorre sitemap.xml e índices de sitemaps (recursivo, 2 niveles)."""
        url = url or source.sitemap_url or urljoin(source.base_url, "/sitemap.xml")
        content = self.http_get(source, url)
        if not content:
            return []
        try:
            root = etree.fromstring(content.encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Sitemap inválido en %s: %s", url, exc)
            return []
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [loc.text.strip() for loc in root.findall(".//sm:loc", ns) if loc.text]
        if root.tag.endswith("sitemapindex") and depth < 2:
            out = []
            for child in locs:
                out += self._discover_sitemap(source, child, depth + 1)
            return out
        return locs

    @api.model
    def _discover_categories(self, source):
        """Rastrea las URLs de categoría configuradas y saca los enlaces de ficha."""
        urls = []
        seen = set()
        for category in source.category_ids.filtered("active"):
            for page_url in category._page_urls():
                content = self.http_get(source, page_url)
                if not content:
                    break
                tree = lxml_html.fromstring(content)
                tree.make_links_absolute(source.base_url)
                found = {
                    a.get("href").split("#")[0]
                    for a in tree.xpath("//a[@href]")
                    if self._is_product_url(source, a.get("href") or "")
                }
                fresh = found - seen
                if not fresh:
                    # página vacía o repetición de la última: fin de la paginación
                    break
                seen |= fresh
                urls += sorted(fresh)
        return urls

    # ------------------------------------------------------------------
    # Parseo de ficha de producto
    # ------------------------------------------------------------------
    @api.model
    def parse_product(self, source, url, content=None):
        """Devuelve un dict normalizado con los datos de la ficha."""
        content = content if content is not None else self.http_get(source, url)
        if not content:
            return {}
        tree = lxml_html.fromstring(content)
        tree.make_links_absolute(source.base_url)

        vals = {
            "url": url,
            "external_id": self._external_id(url),
            "raw_json": False,
        }
        # 1) schema.org (JSON-LD) — lo emiten la mayoría de tiendas y es lo más fiable
        vals.update(self._parse_jsonld(tree))
        # 2) Open Graph / meta como refuerzo
        for key, prop in (("name", "og:title"), ("image_url", "og:image")):
            if not vals.get(key):
                meta = tree.xpath("//meta[@property='%s']/@content" % prop)
                if meta:
                    vals[key] = meta[0].strip()
        # 3) Selectores XPath configurables en la fuente
        vals.update(self._parse_xpath(source, tree))
        # 4) Heurísticas de texto (referencia y EAN)
        text = " ".join(tree.xpath("//body//text()"))
        text = re.sub(r"\s+", " ", text)
        if not vals.get("default_code"):
            match = RE_SKU_LABEL.search(text)
            if match:
                vals["default_code"] = match.group(1).strip(" .:")
        if not vals.get("barcode"):
            for candidate in RE_EAN.findall(text):
                if len(candidate) in (8, 12, 13, 14):
                    vals["barcode"] = candidate
                    break
        if not vals.get("name"):
            title = tree.xpath("//h1//text()") or tree.xpath("//title/text()")
            vals["name"] = title and " ".join(t.strip() for t in title).strip() or False
        if not vals.get("description"):
            desc = tree.xpath("//meta[@name='description']/@content")
            vals["description"] = desc and desc[0].strip() or False
        if not vals.get("categ_path"):
            vals["categ_path"] = self._parse_breadcrumb(tree)
        if vals.get("image_url"):
            vals["image_url"] = urljoin(source.base_url, vals["image_url"])
        vals["price"] = self._parse_price(vals.get("price"))
        vals["name"] = self._clean(vals.get("name"))
        return vals

    @api.model
    def _parse_jsonld(self, tree):
        vals = {}
        for node in tree.xpath("//script[@type='application/ld+json']/text()"):
            try:
                data = json.loads(node)
            except ValueError:
                continue
            for item in self._iter_jsonld(data):
                if (item.get("@type") or "") not in ("Product", "IndividualProduct"):
                    continue
                offers = item.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                brand = item.get("brand")
                if isinstance(brand, dict):
                    brand = brand.get("name")
                vals.update(
                    {
                        "name": item.get("name") or vals.get("name"),
                        "default_code": item.get("sku")
                        or item.get("mpn")
                        or vals.get("default_code"),
                        "barcode": item.get("gtin13")
                        or item.get("gtin")
                        or item.get("gtin14")
                        or item.get("gtin8")
                        or vals.get("barcode"),
                        "description": item.get("description") or vals.get("description"),
                        "brand": brand or vals.get("brand"),
                        "price": offers.get("price") or vals.get("price"),
                        "currency_name": offers.get("priceCurrency")
                        or vals.get("currency_name"),
                        "availability": (offers.get("availability") or "").split("/")[-1]
                        or vals.get("availability"),
                        "raw_json": json.dumps(item, ensure_ascii=False)[:60000],
                    }
                )
                image = item.get("image")
                if isinstance(image, list):
                    image = image[0] if image else None
                if isinstance(image, dict):
                    image = image.get("url")
                if image:
                    vals["image_url"] = image
        return {k: v for k, v in vals.items() if v}

    @api.model
    def _iter_jsonld(self, data):
        if isinstance(data, list):
            for item in data:
                yield from self._iter_jsonld(item)
        elif isinstance(data, dict):
            if "@graph" in data:
                yield from self._iter_jsonld(data["@graph"])
            yield data

    @api.model
    def _parse_breadcrumb(self, tree):
        """Ruta de categoría: BreadcrumbList (JSON-LD), microdatos o .breadcrumb."""
        for node in tree.xpath("//script[@type='application/ld+json']/text()"):
            try:
                data = json.loads(node)
            except ValueError:
                continue
            for item in self._iter_jsonld(data):
                if item.get("@type") != "BreadcrumbList":
                    continue
                names = []
                for element in item.get("itemListElement") or []:
                    target = element.get("item") or {}
                    name = element.get("name") or (
                        target.get("name") if isinstance(target, dict) else None
                    )
                    if name:
                        names.append(str(name).strip())
                if names:
                    return " / ".join(names)
        nodes = tree.xpath(
            "//*[contains(@class,'breadcrumb')]//a//text()"
            " | //*[@itemtype='http://schema.org/BreadcrumbList']//a//text()"
        )
        parts = [self._clean(n) for n in nodes]
        parts = [p for p in parts if p]
        return " / ".join(parts) if parts else False

    @api.model
    def _parse_xpath(self, source, tree):
        vals = {}
        mapping = {
            "name": source.xpath_name,
            "default_code": source.xpath_sku,
            "price": source.xpath_price,
            "description": source.xpath_description,
            "image_url": source.xpath_image,
            "barcode": source.xpath_barcode,
        }
        for field, expr in mapping.items():
            if not expr:
                continue
            try:
                res = tree.xpath(expr)
            except Exception as exc:  # noqa: BLE001
                _logger.warning("XPath inválido '%s': %s", expr, exc)
                continue
            if not res:
                continue
            value = res[0]
            if hasattr(value, "text_content"):
                value = value.text_content()
            value = self._clean(str(value))
            if value:
                vals[field] = value
        return vals

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    @api.model
    def _external_id(self, url):
        match = RE_URL_ID.search(url) or RE_LEGACY_ID.search(url)
        return match.group(1) if match else url.rsplit("/", 1)[-1][:64]

    @api.model
    def _clean(self, value):
        if not value:
            return False
        return re.sub(r"\s+", " ", str(value)).strip() or False

    @api.model
    def _parse_price(self, value):
        """Normaliza '1.234,50 €' / '1,234.50' / 1234.5 a float."""
        if value in (None, False, ""):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        raw = re.sub(r"[^\d,.\-]", "", str(value))
        if not raw:
            return 0.0
        if "," in raw and "." in raw:
            if raw.rfind(",") > raw.rfind("."):  # formato europeo
                raw = raw.replace(".", "").replace(",", ".")
            else:
                raw = raw.replace(",", "")
        elif "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            return 0.0
