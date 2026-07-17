import re
from urllib.parse import urljoin, urlparse

from lxml import html


ANALYTICS_RE = re.compile(
    r"window\.analytics\[['\"]([^'\"]+)['\"]\]\s*=\s*['\"]([^'\"]*)['\"]"
)
CUSTOMER_MEDIA_RE = re.compile(r"/media/customer/([^/]+)/", re.IGNORECASE)
LOCALE_SUFFIX_RE = re.compile(r"_(?:[a-z]{2})(?:_[A-Z]{2})?$", re.IGNORECASE)


def _clean_text(values):
    if not values:
        return False
    if isinstance(values, str):
        values = [values]
    value = " ".join(str(item) for item in values if item is not None)
    return " ".join(value.split()) or False


def _texts(document, xpath):
    return _clean_text(document.xpath(xpath))


def _list_texts(document, xpath):
    result = []
    for node in document.xpath(xpath):
        value = _clean_text(node.xpath(".//text()"))
        if value:
            result.append(value)
    return result


def _meta_content(document, property_name):
    values = document.xpath(
        "//meta[@property=$property]/@content", property=property_name
    )
    return _clean_text(values)


def _brand_name_from_slug(slug):
    if not slug:
        return False
    value = LOCALE_SUFFIX_RE.sub("", slug.strip())
    value = re.sub(r"[-_]+", " ", value).strip()
    if not value:
        return False
    return " ".join(part.capitalize() for part in value.split())


def _extract_brand(document, analytics):
    logo_url = _clean_text(document.xpath("//div[contains(@class, 'top-bar')]//img/@src"))
    brand_slug = False
    if logo_url:
        match = CUSTOMER_MEDIA_RE.search(urlparse(logo_url).path)
        if match:
            brand_slug = match.group(1)

    if not brand_slug:
        catalog_id = analytics.get("catalogId")
        if catalog_id:
            # The customer/catalog prefix is the best fallback exposed by DataView.
            brand_slug = catalog_id.split("_")[0]

    return {
        "name": _brand_name_from_slug(brand_slug),
        "slug": brand_slug,
        "logo_url": logo_url,
    }


def parse_nextmart_html(html_source, source_url=False):
    """Parse a server-rendered Nextmart DataView page.

    The parser only reads stable IDs/classes and returns plain data. It does not
    execute JavaScript and is intentionally independent from Odoo so it can be
    tested without loading an Odoo registry.
    """
    if isinstance(html_source, bytes):
        html_source = html_source.decode("utf-8", errors="replace")

    parser = html.HTMLParser(encoding="utf-8", recover=True)
    document = html.fromstring(html_source, parser=parser, base_url=source_url)

    analytics = dict(ANALYTICS_RE.findall(html_source))

    technical_details = []
    for sequence, row in enumerate(
        document.xpath("//*[@id='nm-product-technical-details-content']//tr"),
        start=10,
    ):
        key = _clean_text(
            row.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' property-key ')]//text()")
        )
        value = _clean_text(
            row.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' property-value ')]//text()")
        )
        if key:
            technical_details.append(
                {"sequence": sequence, "name": key, "value": value or ""}
            )

    images = []
    seen_urls = set()
    for sequence, image in enumerate(
        document.xpath("//*[@id='media-slider']//img[@src]"), start=10
    ):
        image_url = urljoin(source_url or "", (image.get("src") or "").strip())
        if not image_url or image_url in seen_urls:
            continue
        seen_urls.add(image_url)
        images.append(
            {
                "sequence": sequence,
                "url": image_url,
                "kind": (image.get("alt") or "Imagen").strip(),
            }
        )

    og_image = urljoin(
        source_url or "", _meta_content(document, "og:image") or ""
    ) or False
    if og_image and og_image not in seen_urls:
        images.insert(
            0,
            {"sequence": 1, "url": og_image, "kind": "Imagen del producto"},
        )

    details_by_name = {
        item["name"].strip().casefold(): item["value"]
        for item in technical_details
    }

    name = _texts(document, "//*[@id='nm-product-name']//text()")
    description = _texts(
        document, "//*[@id='nm-product-description-long']//text()"
    )

    result = {
        "source_url": source_url,
        "name": name or _meta_content(document, "og:title"),
        "segment": _texts(document, "//*[@id='nm-product-segment']//text()"),
        "description": description or _meta_content(document, "og:description"),
        "marketing_claims": _list_texts(
            document, "//*[@id='nm-product-marketing-claims']/li"
        ),
        "top_features": _list_texts(
            document, "//*[@id='nm-product-top-features']/li"
        ),
        "benefits": _list_texts(
            document, "//*[@id='nm-product-benefits-content']/li"
        ),
        "technical_details": technical_details,
        "images": images,
        "main_image_url": og_image or (images and images[0]["url"]) or False,
        "analytics": analytics,
        "brand": _extract_brand(document, analytics),
        "gtin": details_by_name.get("gtin/ean") or analytics.get("gtin"),
        "manufacturer_reference": (
            details_by_name.get("número de artículo")
            or details_by_name.get("numero de articulo")
            or analytics.get("pid")
        ),
    }
    if result["brand"].get("logo_url"):
        result["brand"]["logo_url"] = urljoin(
            source_url or "", result["brand"]["logo_url"]
        )
    return result
