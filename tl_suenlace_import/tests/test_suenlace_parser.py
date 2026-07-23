# Copyright 2026 Tecniloop
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import base64
from datetime import date

from odoo.tests import TransactionCase

from ..models import suenlace_parser as parser


def _pad(line):
    """Ajusta una línea a 510 caracteres de datos (sin CR/LF)."""
    return line.ljust(510)


class TestSuenlaceParser(TransactionCase):
    """Pruebas unitarias del parser de posiciones fijas."""

    def test_parse_amount(self):
        line = _pad(" " * 99 + "+0000001000.00")
        self.assertAlmostEqual(parser.parse_amount(line, 100), 1000.0)

    def test_parse_amount_negative(self):
        line = _pad(" " * 99 + "-0000000050.25")
        self.assertAlmostEqual(parser.parse_amount(line, 100), -50.25)

    def test_parse_amount_blank(self):
        line = _pad(" " * 120)
        self.assertEqual(parser.parse_amount(line, 100), 0.0)

    def test_parse_date(self):
        line = _pad("5" + "00001" + "20000201")
        self.assertEqual(parser.parse_date(line, 7), date(2000, 2, 1))

    def test_record_type_c_ampliation(self):
        # Posición 15 = 'C', posición 73 = 'B' -> subtipo CB.
        line = _pad("5" + "00001" + "20000201" + "C" + " " * 57 + "B")
        self.assertEqual(parser.record_type(line), "CB")

    def test_parse_type_0_roundtrip(self):
        line = "5" + "00001" + "20000201" + "0"
        line += "6000000000  "                 # cuenta (16-27)
        line += "COMPRAS".ljust(30)            # descripción (28-57)
        line += "D"                            # tipo importe (58)
        line += "DOC001    "                   # referencia (59-68)
        line += "I"                            # línea (69)
        line += "Compra material".ljust(30)    # descripción apunte (70-99)
        line += "+0000001000.00"               # importe (100-113)
        line = _pad(line)
        data = parser.parse_line(line)
        self.assertEqual(data["_type"], "0")
        self.assertEqual(data["cuenta"], "6000000000")
        self.assertEqual(data["tipo_importe"], "D")
        self.assertEqual(data["linea"], "I")
        self.assertAlmostEqual(data["importe"], 1000.0)

    def test_iter_records_counts_types(self):
        header = "5" + "00001" + "20000201"
        line_c = _pad(header + "C" + "4300000001".ljust(12)
                      + "CLIENTE SA".ljust(30))
        line_0 = _pad(header + "0" + "6000000000".ljust(12)
                      + "GASTO".ljust(30) + "D")
        raw = (line_c + "\r\n" + line_0 + "\r\n").encode("cp1252")
        records = list(parser.iter_records(raw))
        types = [r["_type"] for _n, r in records]
        self.assertEqual(types, ["C", "0"])


class TestSuenlacePartnerUtils(TransactionCase):

    def test_normalize_spanish_vat_without_prefix(self):
        from ..models import suenlace_partner_utils as utils
        self.assertEqual(utils.normalize_vat("B-12345674"), "ESB12345674")

    def test_normalize_spanish_vat_with_prefix(self):
        from ..models import suenlace_partner_utils as utils
        self.assertEqual(utils.normalize_vat("es b-12345674"), "ESB12345674")

    def test_normalize_existing_dni_without_prefix(self):
        from ..models import suenlace_partner_utils as utils
        self.assertEqual(utils.normalize_vat("12345678-Z"), "ES12345678Z")

    def test_do_not_force_es_for_explicit_foreign_country(self):
        from ..models import suenlace_partner_utils as utils
        self.assertEqual(utils.normalize_vat("12345678Z", "FR"), "12345678Z")

    def test_vat_equivalence_with_and_without_es(self):
        from ..models import suenlace_partner_utils as utils
        self.assertTrue(utils.vat_equivalent("ESB12345674", "B-12345674"))


class TestSuenlacePartnerMatching(TransactionCase):

    def setUp(self):
        super().setUp()
        self.import_batch = self.env["tl.suenlace.import"].create({
            "company_id": self.env.company.id,
            "file_data": base64.b64encode(b"test"),
            "file_name": "SUENLACE.DAT",
        })

    def test_existing_partner_without_es_is_reused_and_normalized(self):
        partner = self.env["res.partner"].create({
            "name": "Cliente de prueba",
            "vat": "B12345674",
            "country_id": self.env.ref("base.es").id,
        })
        result = self.import_batch._find_or_create_partner({
            "nif": "ESB12345674",
            "nombre": "Cliente de prueba",
            "cuenta": "430000000001",
            "pais": "ES",
        })
        self.assertEqual(result, partner)
        self.assertEqual(result.vat, "ESB12345674")
        self.assertEqual(result.ref, "430000000001")
        self.assertGreaterEqual(result.customer_rank, 1)

    def test_invalid_vat_can_be_imported_when_validation_is_skipped(self):
        self.import_batch.skip_vat_validation = True
        partner = self.import_batch._find_or_create_partner({
            "nif": "ESB00000000",
            "nombre": "NIF pendiente de revisión",
            "cuenta": "430000000099",
            "pais": "ES",
        })
        self.assertEqual(partner.vat, "ESB00000000")

    def test_existing_partner_with_formatted_vat_is_reused(self):
        partner = self.env["res.partner"].create({
            "name": "Persona de prueba",
            "vat": "12345678-Z",
            "country_id": self.env.ref("base.es").id,
            "company_type": "person",
        })
        result = self.import_batch._find_or_create_partner({
            "nif": "ES12345678Z",
            "nombre": "Persona de prueba",
            "pais": "011",
        })
        self.assertEqual(result, partner)
        self.assertEqual(result.vat, "ES12345678Z")


class TestSuenlaceLiteralInvoiceRules(TransactionCase):

    def setUp(self):
        super().setUp()
        self.model = self.env["tl.suenlace.import"]

    def test_sale_invoice_sides(self):
        header = {"_type": "1", "tipo_factura": "1"}
        self.assertEqual(
            self.model._invoice_header_entry_side(header), "debit"
        )
        self.assertEqual(
            self.model._invoice_detail_entry_side(
                header, {"tipo_importe": "C"}
            ),
            "credit",
        )

    def test_purchase_invoice_sides(self):
        header = {"_type": "1", "tipo_factura": "2"}
        self.assertEqual(
            self.model._invoice_header_entry_side(header), "credit"
        )
        self.assertEqual(
            self.model._invoice_detail_entry_side(
                header, {"tipo_importe": "C"}
            ),
            "debit",
        )

    def test_refund_and_abono_reverse_sides(self):
        header = {"_type": "2", "tipo_factura": "1"}
        self.assertEqual(
            self.model._invoice_header_entry_side(header), "credit"
        )
        self.assertEqual(
            self.model._invoice_detail_entry_side(
                header, {"tipo_importe": "C"}
            ),
            "debit",
        )
        self.assertEqual(
            self.model._invoice_detail_entry_side(
                header, {"tipo_importe": "A"}
            ),
            "credit",
        )

    def test_negative_amount_reverses_side(self):
        self.assertEqual(
            self.model._amount_to_debit_credit(-25.0, "debit"),
            (0.0, 25.0),
        )
