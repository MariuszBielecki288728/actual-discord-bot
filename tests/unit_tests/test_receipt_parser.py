from datetime import date
from decimal import Decimal

import pytest

from actual_discord_bot.receipts.models import ParsedReceipt, ReceiptItem
from actual_discord_bot.receipts.parser import ReceiptParser


@pytest.fixture
def parser():
    return ReceiptParser()


class TestReceiptParser:
    """Test full receipt text → ParsedReceipt conversion."""

    def test_parse_simple_receipt(self, parser):
        text = """\
Bar Pierożek Trzeciak
Wrocław, 50-046
NIP 8992878275
PARAGON FISKALNY nr:97584
Pierogi ruskie 330g 1 x26,70 26,70B
Barszcz z uszkami 480 ml 1 x25,50 25,50B
Dostawa 1 x4,99 4,99A
Kompot 250 ml 1 x17,30 17,30B
SPRZEDAŻ OPODATKOWANA A 4,99
SPRZEDAŻ OPODATKOWANA B 69,50
SUMA PLN 74,49
2026-04-24 14:38
"""
        receipt = parser.parse(text, source="photo")

        assert receipt.store_name == "Bar Pierożek Trzeciak"
        assert receipt.total == Decimal("74.49")
        assert receipt.date == date(2026, 4, 24)
        assert receipt.source == "photo"
        assert len(receipt.items) == 4
        assert receipt.items[0].name == "Pierogi ruskie 330g"
        assert receipt.items[0].total_price == Decimal("26.70")
        assert receipt.items[0].quantity == Decimal("1")
        assert receipt.items[1].name == "Barszcz z uszkami 480 ml"
        assert receipt.items[2].name == "Dostawa"
        assert receipt.items[2].vat_category == "A"
        assert receipt.items[3].name == "Kompot 250 ml"

    def test_parse_receipt_with_multiplier_star(self, parser):
        """Test parsing with * multiplier and szt/= format (Społem/Stodoła Market)."""
        text = """\
STODOŁA MARKET
PARAGON FISKALNY
SMALEC/MIESO/CZOSN 1 szt * 4,90 = 4,90 D
MLEKO ŁACIATE BUT. 1 szt * 3,40 = 3,40 D
BUŁKA MONTOWA 100G 4 szt * 1,25 = 5,00 D
SUMA PLN 13,30
"""
        receipt = parser.parse(text, source="photo")
        assert receipt.store_name == "STODOŁA MARKET"
        assert receipt.total == Decimal("13.30")
        assert len(receipt.items) == 3
        assert receipt.items[0].name == "SMALEC/MIESO/CZOSN"
        assert receipt.items[0].total_price == Decimal("4.90")
        assert receipt.items[2].name == "BUŁKA MONTOWA 100G"
        assert receipt.items[2].quantity == Decimal("4")
        assert receipt.items[2].total_price == Decimal("5.00")

    def test_parse_receipt_with_discount(self, parser):
        text = """\
ORLEN
PARAGON FISKALNY
EFECTA DIESEL 30 x7,79 233,70B
OBNIŻKA -2,40B
SPRZEDAŻ OPODATKOWANA B 231,30
SUMA PLN 231,30
2026-04-18 18:50
"""
        receipt = parser.parse(text, source="photo")

        assert receipt.store_name == "ORLEN"
        assert receipt.total == Decimal("231.30")
        assert len(receipt.items) == 2
        assert receipt.items[0].name == "EFECTA DIESEL"
        assert receipt.items[0].total_price == Decimal("233.70")
        assert receipt.items[1].is_discount is True
        assert receipt.items[1].total_price == Decimal("-2.40")

    def test_parse_receipt_with_multiline_item(self, parser):
        text = """\
Folgujemy
PARAGON FISKALNY
Barszcz z uszkami z podgrzybków 480 ml
                       1 x25,50 25,50B
Pierogi ruskie 330g 1 x26,70 26,70B
SUMA PLN 52,20
"""
        receipt = parser.parse(text, source="photo")

        assert len(receipt.items) == 2
        assert receipt.items[0].name == "Barszcz z uszkami z podgrzybków 480 ml"
        assert receipt.items[0].total_price == Decimal("25.50")
        assert receipt.items[1].name == "Pierogi ruskie 330g"

    def test_parse_pdf_source(self, parser):
        text = """\
Kaufland
PARAGON FISKALNY
Mleko 3.2% 1l 1 x4,99 4,99B
Chleb 500g 1 x5,49 5,49D
SUMA PLN 10,48
2026-04-30
"""
        receipt = parser.parse(text, source="pdf")
        assert receipt.source == "pdf"
        assert receipt.total == Decimal("10.48")

    def test_no_header_still_parses(self, parser):
        """If receipt has no PARAGON FISKALNY header, still try to find items."""
        text = """\
Sklep Testowy
Mleko 1 x3,50 3,50B
Chleb 1 x4,00 4,00D
SUMA PLN 7,50
"""
        receipt = parser.parse(text, source="photo")
        assert receipt.store_name == "Sklep Testowy"
        assert receipt.total == Decimal("7.50")
        assert len(receipt.items) == 2

    def test_empty_text(self, parser):
        receipt = parser.parse("", source="photo")
        assert receipt.store_name == "Unknown"
        assert receipt.total == Decimal("0")
        assert receipt.items == []


class TestDateExtraction:
    """Test date parsing from various receipt formats."""

    def test_standard_date_format(self, parser):
        text = "Some receipt\nSUMA PLN 10,00\n2026-04-24 14:38\n"
        receipt = parser.parse(text)
        assert receipt.date == date(2026, 4, 24)

    def test_date_without_time(self, parser):
        text = "Some receipt\nSUMA PLN 10,00\n2026-04-30\n"
        receipt = parser.parse(text)
        assert receipt.date == date(2026, 4, 30)

    def test_no_date_returns_none(self, parser):
        text = "Some receipt\nSUMA PLN 10,00\n"
        receipt = parser.parse(text)
        assert receipt.date is None


class TestTotalExtraction:
    """Test total amount extraction."""

    def test_suma_pln_format(self, parser):
        text = "Store\nPARAGON FISKALNY\nItem 1 x10,00 10,00B\nSUMA PLN 10,00\n"
        receipt = parser.parse(text)
        assert receipt.total == Decimal("10.00")

    def test_razem_format(self, parser):
        text = "Store\nPARAGON FISKALNY\nItem 1 x5,50 5,50B\nRAZEM 5,50\n"
        receipt = parser.parse(text)
        assert receipt.total == Decimal("5.50")

    def test_suma_with_colon(self, parser):
        text = "Store\nPARAGON FISKALNY\nItem 1 x25,99 25,99B\nSUMA: 25,99\n"
        receipt = parser.parse(text)
        assert receipt.total == Decimal("25.99")


class TestReceiptLineParser:
    """Test individual line parsing patterns."""

    def test_standard_line(self, parser):
        text = "Store\nPARAGON FISKALNY\nPierogi ruskie 330g 1 x26,70 26,70B\nSUMA PLN 26,70\n"
        receipt = parser.parse(text)
        assert len(receipt.items) == 1
        item = receipt.items[0]
        assert item.name == "Pierogi ruskie 330g"
        assert item.quantity == Decimal("1")
        assert item.unit_price == Decimal("26.70")
        assert item.total_price == Decimal("26.70")
        assert item.vat_category == "B"

    def test_multiple_quantity(self, parser):
        text = "Store\nPARAGON FISKALNY\nBułka 4 x1,25 5,00D\nSUMA PLN 5,00\n"
        receipt = parser.parse(text)
        item = receipt.items[0]
        assert item.quantity == Decimal("4")
        assert item.unit_price == Decimal("1.25")
        assert item.total_price == Decimal("5.00")

    def test_discount_line(self, parser):
        text = "Store\nPARAGON FISKALNY\nItem 1 x10,00 10,00B\nOBNIŻKA -1,50B\nSUMA PLN 8,50\n"
        receipt = parser.parse(text)
        assert len(receipt.items) == 2
        assert receipt.items[1].is_discount is True
        assert receipt.items[1].total_price == Decimal("-1.50")

    def test_tax_section_stops_parsing(self, parser):
        text = """\
Store
PARAGON FISKALNY
Item1 1 x10,00 10,00B
Item2 1 x5,00 5,00A
SPRZEDAŻ OPODATKOWANA A 5,00
SPRZEDAŻ OPODATKOWANA B 10,00
PTU A 23% 0,93
SUMA PLN 15,00
"""
        receipt = parser.parse(text)
        assert len(receipt.items) == 2

    def test_article_code_stripped(self, parser):
        text = "Store\nPARAGON FISKALNY\n63338001 t-shirt mes 1 x30,00 30,00A\nSUMA PLN 30,00\n"
        receipt = parser.parse(text)
        assert receipt.items[0].name == "t-shirt mes"


class TestTotalValidation:
    """Test sum of items vs. declared total."""

    def test_valid_receipt(self):
        receipt = ParsedReceipt(
            store_name="Test",
            items=[
                ReceiptItem("A", Decimal("1"), Decimal("10.00"), Decimal("10.00")),
                ReceiptItem("B", Decimal("1"), Decimal("5.00"), Decimal("5.00")),
            ],
            total=Decimal("15.00"),
        )
        from actual_discord_bot.receipts.handler import ReceiptHandler

        is_valid, diff = ReceiptHandler.validate_receipt(receipt)
        assert is_valid is True
        assert diff == Decimal("0")

    def test_small_rounding_difference(self):
        receipt = ParsedReceipt(
            store_name="Test",
            items=[
                ReceiptItem("A", Decimal("1"), Decimal("10.00"), Decimal("10.00")),
                ReceiptItem("B", Decimal("1"), Decimal("5.01"), Decimal("5.01")),
            ],
            total=Decimal("15.00"),
        )
        from actual_discord_bot.receipts.handler import ReceiptHandler

        is_valid, diff = ReceiptHandler.validate_receipt(receipt)
        assert is_valid is True
        assert diff == Decimal("-0.01")

    def test_large_mismatch(self):
        receipt = ParsedReceipt(
            store_name="Test",
            items=[
                ReceiptItem("A", Decimal("1"), Decimal("10.00"), Decimal("10.00")),
            ],
            total=Decimal("15.00"),
        )
        from actual_discord_bot.receipts.handler import ReceiptHandler

        is_valid, diff = ReceiptHandler.validate_receipt(receipt)
        assert is_valid is False
        assert diff == Decimal("5.00")


class TestDigitalReceiptParser:
    """Test parsing of digital receipt PDFs (Kaufland-style format)."""

    def test_kaufland_digital_format(self, parser):
        text = """\
Podsumowanie zakupów
Kaufland Wrocław-Szczepin
ul. Długa 37/47
Wrocław
Cena w
2,99
MuszyniankaWoda1,5L
2,99
MuszyniankaWoda1,5L
39,99
CoccolinoCareŻel28pr
6,59
Kinder Bueno white rożek
126,08
Suma
none
Podatek % Brutto Netto Podatek
A 23 % 54,54 44,34 10,20
Data: 08.08.2025 Czas: 20:00
"""
        receipt = parser.parse(text, source="pdf")

        assert receipt.store_name == "Kaufland Wrocław-Szczepin"
        assert receipt.total == Decimal("126.08")
        assert receipt.date == date(2025, 8, 8)
        assert receipt.source == "pdf"
        assert len(receipt.items) == 4
        assert receipt.items[0].name == "MuszyniankaWoda1,5L"
        assert receipt.items[0].total_price == Decimal("2.99")
        assert receipt.items[2].name == "CoccolinoCareŻel28pr"
        assert receipt.items[2].total_price == Decimal("39.99")

    def test_date_dot_format(self, parser):
        """Test DD.MM.YYYY date format used in digital receipts."""
        text = """\
Podsumowanie zakupów
Store
Cena w
5,00
Item
5,00
Suma
Data: 15.03.2026 Czas: 10:30
"""
        receipt = parser.parse(text, source="pdf")
        assert receipt.date == date(2026, 3, 15)


class TestWeightedItems:
    """Test parsing of weighted/measured items."""

    def test_weighted_item_with_kg(self, parser):
        text = "Store\nPARAGON FISKALNY\nBanany x1.234kg 8,72A\nSUMA PLN 8,72\n"
        receipt = parser.parse(text)
        assert len(receipt.items) == 1
        item = receipt.items[0]
        assert item.name == "Banany"
        assert item.quantity == Decimal("1.234")
        assert item.total_price == Decimal("8.72")

    def test_weighted_item_with_comma(self, parser):
        text = "Store\nPARAGON FISKALNY\nJabłka x2,500kg 12,50B\nSUMA PLN 12,50\n"
        receipt = parser.parse(text)
        assert len(receipt.items) == 1
        item = receipt.items[0]
        assert item.name == "Jabłka"
        assert item.quantity == Decimal("2.500")


class TestOCRFormat:
    """Test parsing of OCR-typical format with = signs and szt."""

    def test_ocr_format_with_szt(self, parser):
        """Test format: name qty szt * unit_price = total_price vat"""
        text = "Store\nPARAGON FISKALNY\nMLEKO 2 szt * 3,40 = 6,80 D\nSUMA PLN 6,80\n"
        receipt = parser.parse(text)
        assert len(receipt.items) == 1
        item = receipt.items[0]
        assert item.name == "MLEKO"
        assert item.quantity == Decimal("2")
        assert item.unit_price == Decimal("3.40")
        assert item.total_price == Decimal("6.80")

    def test_ocr_weighted_with_kg(self, parser):
        """Test OCR format with kg weight."""
        text = (
            "Store\nPARAGON FISKALNY\nBanany 1,234 kg * 7,99 = 9,86 D\nSUMA PLN 9,86\n"
        )
        receipt = parser.parse(text)
        assert len(receipt.items) == 1
        item = receipt.items[0]
        assert item.name == "Banany"
        assert item.quantity == Decimal("1.234")

    def test_discount_summary_skipped(self, parser):
        """Discount summary line should not be parsed as an item."""
        text = """\
Store
PARAGON FISKALNY
Item1 1 x10,00 10,00B
OBNIŻKA -2,00B
Suma obniżek: 2,00
SUMA PLN 8,00
"""
        receipt = parser.parse(text)
        # Should have 2 items (item + discount), NOT 3
        assert len(receipt.items) == 2
        assert receipt.items[0].name == "Item1"
        assert receipt.items[1].is_discount is True


class TestDateDotFormat:
    """Test DD.MM.YYYY date format extraction."""

    def test_date_dot_format_basic(self, parser):
        text = "Store\nPARAGON FISKALNY\nItem 1 x10,00 10,00B\nSUMA PLN 10,00\nData: 24.04.2026\n"
        receipt = parser.parse(text)
        assert receipt.date == date(2026, 4, 24)

    def test_date_dot_format_without_prefix(self, parser):
        text = "Store\nPARAGON FISKALNY\nItem 1 x10,00 10,00B\nSUMA PLN 10,00\n24.04.2026\n"
        receipt = parser.parse(text)
        assert receipt.date == date(2026, 4, 24)


class TestDiscountVariants:
    """Test different discount wording (OBNIŻKA, RABAT, UPUST)."""

    def test_rabat_discount(self, parser):
        text = "Store\nPARAGON FISKALNY\nItem 1 x10,00 10,00B\nRABAT -1,00B\nSUMA PLN 9,00\n"
        receipt = parser.parse(text)
        assert len(receipt.items) == 2
        assert receipt.items[1].is_discount is True
        assert receipt.items[1].name == "RABAT"
        assert receipt.items[1].total_price == Decimal("-1.00")

    def test_upust_discount(self, parser):
        text = "Store\nPARAGON FISKALNY\nItem 1 x10,00 10,00B\nUPUST -0,50B\nSUMA PLN 9,50\n"
        receipt = parser.parse(text)
        assert len(receipt.items) == 2
        assert receipt.items[1].is_discount is True
        assert receipt.items[1].total_price == Decimal("-0.50")
