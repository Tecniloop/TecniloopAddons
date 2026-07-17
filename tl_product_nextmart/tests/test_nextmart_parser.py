from odoo.tests.common import TransactionCase

from ..tools import parse_nextmart_html


SAMPLE = """
<html lang="es">
<head>
<meta property="og:title" content="Sample product"/>
<meta property="og:image" content="https://www.nexmart.com/media/sample.jpg"/>
</head>
<body>
<div class="top-bar"><img src="https://www.nexmart.com/media/customer/bosch/logo/logo.png"/></div>
<h1 id="nm-product-name">Sample product</h1>
<div id="nm-product-description-long">Long description</div>
<table id="nm-product-technical-details-content">
<tr><td class="property-key">GTIN/EAN</td><td class="property-value">3165140795777</td></tr>
<tr><td class="property-key">Número de artículo</td><td class="property-value">2608644011</td></tr>
</table>
<div id="media-slider"><img src="https://www.nexmart.com/media/sample.jpg" alt="Imagen del producto"/></div>
<script>
window.analytics['gtin'] = "3165140795777";
window.analytics['supplierId'] = "C000022";
window.analytics['catalogId'] = "bosch_expert_es";
window.analytics['pid'] = "2608644011";
</script>
</body>
</html>
"""


class TestNextmartParser(TransactionCase):
    def test_parser(self):
        data = parse_nextmart_html(SAMPLE)
        self.assertEqual(data["gtin"], "3165140795777")
        self.assertEqual(data["manufacturer_reference"], "2608644011")
        self.assertEqual(data["brand"]["name"], "Bosch")
        self.assertEqual(len(data["technical_details"]), 2)
        self.assertEqual(len(data["images"]), 1)
