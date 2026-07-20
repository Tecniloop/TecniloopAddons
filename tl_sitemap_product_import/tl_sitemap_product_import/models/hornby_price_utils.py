"""Utilidades de localización de precios para las tiendas de Hornby Hobbies.

Las marcas internacionales de Hornby comparten plataforma y rutas de producto,
pero publican precios distintos según el mercado. El importador no convierte
monedas: cambia al escaparate oficial que vende en EUR y lee allí el precio.
"""

from urllib.parse import urlsplit, urlunsplit


# Mercados oficiales en euros comprobados para las marcas Hornby International.
# Los conectores de las marcas continentales reutilizan esta tabla para
# resolver la ficha oficial equivalente en EUR sin convertir divisas.
HORNBY_EUR_HOST_MAP = {
    'uk.jouef.com': ('fr.jouef.com',),
    'fr.jouef.com': ('fr.jouef.com',),
    'es.electrotren.com': ('es.electrotren.com',),
    'de.arnoldmodel.com': ('de.arnoldmodel.com',),
    'uk.arnoldmodel.com': ('de.arnoldmodel.com',),
    'it.rivarossi.com': ('it.rivarossi.com',),
    'uk.rivarossi.com': ('it.rivarossi.com',),
    'it.limamodel.it': ('it.limamodel.it',),
    'uk.limamodel.it': ('it.limamodel.it',),
}


def normalise_host(value):
    """Devuelve un host comparable, sin puerto ni prefijo ``www``."""
    host = str(value or '').strip().casefold().split('@')[-1].split(':', 1)[0]
    return host[4:] if host.startswith('www.') else host


def eur_hosts_for_url(product_url, explicit_hosts=None):
    """Obtiene los escaparates oficiales en EUR para una URL Hornby."""
    if explicit_hosts:
        values = explicit_hosts
    else:
        values = HORNBY_EUR_HOST_MAP.get(
            normalise_host(urlsplit(str(product_url or '')).netloc),
            (),
        )
    result = []
    for value in values or ():
        host = normalise_host(value)
        if host and host not in result:
            result.append(host)
    return tuple(result)


def eur_product_urls(product_url, explicit_hosts=None):
    """Genera las URLs equivalentes del producto en los mercados EUR.

    Hornby mantiene normalmente la misma ruta ``/products/<slug>`` entre
    escaparates. Se eliminan consulta y fragmento para no arrastrar parámetros
    de seguimiento o selección de mercado.
    """
    raw = str(product_url or '').strip()
    if not raw:
        return []
    parts = urlsplit(raw)
    if not parts.path:
        return []
    result = []
    for host in eur_hosts_for_url(raw, explicit_hosts=explicit_hosts):
        candidate = urlunsplit(('https', host, parts.path, '', ''))
        if candidate not in result:
            result.append(candidate)
    return result
