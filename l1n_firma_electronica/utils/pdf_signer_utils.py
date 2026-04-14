import io
import logging
from urllib.parse import urlparse

from pyhanko.sign import signers
from pyhanko.sign.fields import SigFieldSpec, SigSeedSubFilter
from pyhanko.sign.signers.pdf_signer import PdfSignatureMetadata
from pyhanko.sign.timestamps import HTTPTimeStamper

from pyhanko.pdf_utils import generic
from pyhanko.pdf_utils.generic import pdf_name
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

_logger = logging.getLogger(__name__)

DEFAULT_TSA_LIST = [
    "https://rfc3161timestamp.globalsign.com/advanced",
    "https://rfc3161timestamp.globalsign.com/qualified",
    "http://timestamp.digicert.com",
    "http://timestamp.sectigo.com",
]


def _normalize_tsa_url(url):
    value = (url or "").strip()

    if not value:
        return ""

    parsed = urlparse(value)

    if not parsed.scheme:
        value = f"http://{value}"

    return value


def _get_tsa_candidates(tsa_url=None):
    candidates = []

    normalized = _normalize_tsa_url(tsa_url)

    if normalized:
        candidates.append(normalized)

    candidates.extend(DEFAULT_TSA_LIST)

    deduplicated = []

    for candidate in candidates:
        if candidate not in deduplicated:
            deduplicated.append(candidate)

    return deduplicated


def _asegurar_campos_formulario(writer):
    root = writer.root

    if "/AcroForm" not in root:
        form = generic.DictionaryObject()

        root[pdf_name("/AcroForm")] = writer.add_object(form)

        form[pdf_name("/Fields")] = generic.ArrayObject()

        writer.update_root()

    else:
        form = root["/AcroForm"]

        if "/Fields" not in form:
            form[pdf_name("/Fields")] = generic.ArrayObject()

            writer.update_container(form)


def sign_pdf_pades(
    pdf_bytes,
    pfx_bytes,
    passphrase,
    user_name,
    tsa_url=None,
    enable_timestamp=False,
):
    """
    Firma PDF en formato PAdES-B (por defecto)
    y opcionalmente PAdES-B-T si enable_timestamp=True.
    Compatible con pyHanko 0.34.x
    """

    password_bytes = (
        passphrase.encode("utf-8")
        if passphrase
        else None
    )

    signer = signers.SimpleSigner.load_pkcs12_data(
        pkcs12_bytes=pfx_bytes,
        passphrase=password_bytes,
        other_certs=[]
    )

    signature_meta = PdfSignatureMetadata(
        field_name="Firma1",
        subfilter=SigSeedSubFilter.PADES,
        reason="Firma Electrónica Certificada",
        location="España",
        name=user_name,
    )

    if not enable_timestamp:
        writer = IncrementalPdfFileWriter(
            io.BytesIO(pdf_bytes)
        )

        _asegurar_campos_formulario(writer)

        output = signers.sign_pdf(
            writer,
            signature_meta=signature_meta,
            signer=signer,
            new_field_spec=SigFieldSpec(
                sig_field_name="Firma1",
                on_page=-1,
                box=(360, 20, 560, 90),
            ),
        )

        _logger.info(
            "Firma generada en modo PAdES-B (timestamp desactivado)."
        )

        return output.read()

    errors = []

    for endpoint in _get_tsa_candidates(tsa_url):

        try:

            writer = IncrementalPdfFileWriter(
                io.BytesIO(pdf_bytes)
            )

            _asegurar_campos_formulario(writer)

            timestamper = HTTPTimeStamper(
                url=endpoint,
            )

            output = signers.sign_pdf(
                writer,
                signature_meta=signature_meta,
                signer=signer,
                timestamper=timestamper,
                new_field_spec=SigFieldSpec(
                    sig_field_name="Firma1",
                    on_page=-1,
                    box=(360, 20, 560, 90),
                ),
            )

            _logger.info(
                "Firma generada correctamente con TSA: %s",
                endpoint,
            )

            return output.read()

        except Exception as endpoint_error:

            errors.append(
                f"{endpoint}: {endpoint_error}"
            )

            _logger.warning(
                "Fallo TSA en %s: %s",
                endpoint,
                endpoint_error,
            )

    try:
        writer = IncrementalPdfFileWriter(
            io.BytesIO(pdf_bytes)
        )

        _asegurar_campos_formulario(writer)

        output = signers.sign_pdf(
            writer,
            signature_meta=signature_meta,
            signer=signer,
            new_field_spec=SigFieldSpec(
                sig_field_name="Firma1",
                on_page=-1,
                box=(360, 20, 560, 90),
            ),
        )

        _logger.warning(
            "No se pudo obtener timestamp RFC3161. "
            "Se devolvió firma PAdES-B sin sello de tiempo. Errores TSA: %s",
            " | ".join(errors),
        )

        return output.read()

    except Exception as fallback_error:
        raise RuntimeError(
            "No se pudo obtener timestamp válido y tampoco firmar sin timestamp. "
            + "Errores TSA: " + " | ".join(errors)
            + " | Error fallback: " + str(fallback_error)
        )
