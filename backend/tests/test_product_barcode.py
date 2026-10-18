"""Выбор товарного штрихкода и подпись размера на этикетке."""
import io

from app.services.product_barcode import choose_product_barcode


def test_prefers_barcode_starting_with_zero() -> None:
    assert choose_product_barcode(["2050946628590", "04630723531138"]) == "04630723531138"


def test_keeps_old_barcode_when_no_zero_prefix() -> None:
    assert choose_product_barcode(["2050946628590"]) == "2050946628590"
    assert choose_product_barcode(["OZN2396435883"]) == "OZN2396435883"


def test_ozon_fallback_is_ozn_when_catalog_has_no_zero_code() -> None:
    assert choose_product_barcode(["2000123456789"], fallback="OZN123") == "OZN123"
    assert choose_product_barcode([], fallback="OZN123") == "OZN123"
    assert choose_product_barcode(["2000123456789", "04601234567890"], fallback="OZN123") == "04601234567890"


def test_empty_and_duplicates() -> None:
    assert choose_product_barcode([]) is None
    assert choose_product_barcode(None) is None
    assert choose_product_barcode(["", " 0461 ", "0461", "2000"]) == "0461"


def test_two_zero_codes_keep_the_first() -> None:
    assert choose_product_barcode(["04611111111111", "04622222222222"]) == "04611111111111"


def test_wb_pdf_shows_size_for_14_digit_code() -> None:
    from pypdf import PdfReader

    from app.api.v1.endpoints.orders import _generate_product_barcode_pdf

    pdf = _generate_product_barcode_pdf(
        "04630723531138",
        "04630723531138",
        "obe_flamingo_black",
        "L / 50-52",
        show_size=True,
    )
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text() or ""
    assert "04630723531138" in text
    assert "50-52" in text
    assert "obe_flamingo_black" in text
