# Copyright 2026 Custom Development
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Shared fixtures for the product_icecat test suite.

``SAMPLE_PRODUCT_XML`` is a hand-built, minimal-but-representative Icecat
``productxml`` response, covering every element/attribute
``models.icecat_api.IcecatProduct`` reads: identifiers, EAN, category,
short/long description, a couple of technical features grouped under one
feature group, and a two-picture gallery (one flagged as main). It mirrors
the real schema confirmed against a live Icecat fixture during development,
not a guess.
"""
from xml.etree import ElementTree as ET

from ..models.icecat_api import IcecatProduct

SAMPLE_PRODUCT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ICECAT-interface>
  <Product ID="12345" Prod_id="TEST-MPN-001" Title="Acme Widget Pro 15"
           Quality="ICECAT" HighPic="https://images.example.com/main.jpg">
    <EANCode EAN="1234567890123"/>
    <Supplier ID="99" Name="Acme"/>
    <Category ID="555">
      <Name Value="Widgets"/>
    </Category>
    <SummaryDescription>
      <ShortSummaryDescription>Acme Widget Pro 15, 15.6 inch, Black</ShortSummaryDescription>
      <LongSummaryDescription>Acme Widget Pro 15. Display diagonal: 15.6 inch. Colour: Black.</LongSummaryDescription>
    </SummaryDescription>
    <ProductDescription LongDesc="&lt;b&gt;Premium widget&lt;/b&gt; for professionals." ShortDesc="Premium widget"/>
    <CategoryFeatureGroup ID="1001" No="50">
      <FeatureGroup ID="5">
        <Name Value="Display"/>
      </FeatureGroup>
    </CategoryFeatureGroup>
    <ProductFeature CategoryFeatureGroup_ID="1001" No="100" Value="15.6" Presentation_Value="15.6 inch">
      <Feature><Name Value="Display diagonal"/></Feature>
    </ProductFeature>
    <ProductFeature CategoryFeatureGroup_ID="1001" No="90" Value="Black" Presentation_Value="Black">
      <Feature><Name Value="Colour"/></Feature>
    </ProductFeature>
    <ProductGallery>
      <ProductPicture IsMain="Y" Pic="https://images.example.com/main.jpg"/>
      <ProductPicture Pic="https://images.example.com/gallery1.jpg"/>
    </ProductGallery>
  </Product>
</ICECAT-interface>
"""

SAMPLE_PRODUCT_XML_ERROR = b"""<?xml version="1.0" encoding="UTF-8"?>
<ICECAT-interface>
  <Product ErrorMessage="The requested XML data-sheet is not present in the Icecat database."/>
</ICECAT-interface>
"""

# Minimal-but-representative ``SuppliersList.xml.gz`` content, mirroring the
# real refs export schema: ``<Supplier>`` entries with numeric ``ID`` and
# ``Name`` attributes, wrapped in Icecat's usual interface/response envelope.
SAMPLE_SUPPLIERS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ICECAT-interface>
  <Response Date="2026-07-18" Status="1">
    <SuppliersList Code="1">
      <Supplier ID="1" Name="HP" LogoPic="https://images.example.com/hp.png"/>
      <Supplier ID="99" Name="Acme "/>
      <Supplier ID="734" Name="Lenovo"/>
      <Supplier Name="No ID, skipped"/>
      <Supplier ID="800"/>
    </SuppliersList>
  </Response>
</ICECAT-interface>
"""


def gzip_bytes(data):
    """Gzip-compress ``data``, the way Icecat serves its refs exports."""
    import gzip
    import io

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz_file:
        gz_file.write(data)
    return buf.getvalue()


# A tiny 1x1 transparent PNG, used wherever a test needs to stand in for a
# downloaded product image without making a real HTTP call.
TINY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def get_test_product(xml=SAMPLE_PRODUCT_XML):
    """Parse ``xml`` (defaulting to :data:`SAMPLE_PRODUCT_XML`) into an
    :class:`~odoo.addons.product_icecat.models.icecat_api.IcecatProduct`,
    the same way :meth:`IcecatClient.get_product_by_part_number` does."""
    root = ET.fromstring(xml)
    return IcecatProduct(root.find("Product"))
