from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.properties import PageSetupProperties

OZON_FIRST_COLUMN = "Номер заказа"
WB_FIRST_COLUMN = "№ задания"
OZON_ARTICLE_COLUMN = "Артикул"
OZON_QTY_COLUMN = "Количество"
WB_SIZE_COLUMN = "Размер"
WB_ARTICLE_COLUMN = "Артикул продавца"
ROWS_PER_COLUMN = 67


@dataclass(slots=True)
class SourceFile:
    path: Path
    source_type: str  # "ozon" | "wb"


def process_files(input_paths: list[Path], output_dir: Path) -> tuple[Path, dict[str, int]]:
    classified = [SourceFile(path=p, source_type=detect_source_type(p)) for p in input_paths]

    ozon_articles: list[str] = []
    wb_articles: list[str] = []

    for source in classified:
        if source.source_type == "ozon":
            ozon_articles.extend(parse_ozon_articles(source.path))
        elif source.source_type == "wb":
            wb_articles.extend(parse_wb_articles(source.path))

    workbook = Workbook()
    ozon_ws = workbook.active
    ozon_ws.title = "ozon"
    wb_ws = workbook.create_sheet("wb")

    _fill_sheet(ozon_ws, "ozon", ozon_articles)
    _fill_sheet(wb_ws, "wb", wb_articles)

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y-%m-%d')}.xlsx"
    output_path = output_dir / filename
    workbook.save(output_path)

    return output_path, {"ozon": len(ozon_articles), "wb": len(wb_articles)}


def detect_source_type(file_path: Path) -> str:
    wb = load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    first_header = _normalize_header(ws.cell(row=1, column=1).value)
    wb.close()

    if first_header == _normalize_header(OZON_FIRST_COLUMN):
        return "ozon"
    if first_header == _normalize_header(WB_FIRST_COLUMN):
        return "wb"

    raise ValueError(
        f"Файл {file_path.name} не распознан. Первый столбец должен быть "
        f"'{OZON_FIRST_COLUMN}' или '{WB_FIRST_COLUMN}'."
    )


def parse_ozon_articles(file_path: Path) -> list[str]:
    wb = load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    header_map = _header_map(ws.iter_rows(min_row=1, max_row=1, values_only=True))

    if OZON_ARTICLE_COLUMN not in header_map or OZON_QTY_COLUMN not in header_map:
        wb.close()
        raise ValueError(
            f"Файл {file_path.name}: ожидаются столбцы '{OZON_ARTICLE_COLUMN}' и '{OZON_QTY_COLUMN}'."
        )

    article_idx = header_map[OZON_ARTICLE_COLUMN]
    qty_idx = header_map[OZON_QTY_COLUMN]

    rows: list[tuple[str, int]] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        article_raw = row[article_idx] if article_idx < len(row) else None
        qty_raw = row[qty_idx] if qty_idx < len(row) else None

        article = str(article_raw).strip() if article_raw is not None else ""
        if not article:
            continue

        qty = _parse_qty(qty_raw)
        rows.append((article, qty))

    wb.close()

    current_count = len(rows)
    qty_sum = sum(qty for _, qty in rows)

    if qty_sum != current_count and qty_sum > current_count:
        expanded: list[str] = []
        for article, qty in rows:
            expanded.extend([article] * qty)
        return expanded

    return [article for article, _ in rows]


def parse_wb_articles(file_path: Path) -> list[str]:
    wb = load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    header_map = _header_map(ws.iter_rows(min_row=1, max_row=1, values_only=True))

    if WB_SIZE_COLUMN not in header_map or WB_ARTICLE_COLUMN not in header_map:
        wb.close()
        raise ValueError(
            f"Файл {file_path.name}: ожидаются столбцы '{WB_SIZE_COLUMN}' и '{WB_ARTICLE_COLUMN}'."
        )

    size_idx = header_map[WB_SIZE_COLUMN]
    article_idx = header_map[WB_ARTICLE_COLUMN]

    result: list[str] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        article_raw = row[article_idx] if article_idx < len(row) else None
        size_raw = row[size_idx] if size_idx < len(row) else None

        article = str(article_raw).strip() if article_raw is not None else ""
        size = str(size_raw).strip() if size_raw is not None else ""

        if not article and not size:
            continue
        result.append(f"{article}_{size}".strip("_"))

    wb.close()
    return result


def _fill_sheet(ws, sheet_label: str, articles: list[str]) -> None:
    sorted_articles = sorted(articles, key=lambda x: x.lower())
    white_articles = [a for a in sorted_articles if "white" in a.lower()]
    main_articles = [a for a in sorted_articles if "white" not in a.lower()]

    ws["A1"] = sheet_label
    ws["B1"] = len(sorted_articles)

    used_columns = _write_blocks(ws, start_column=1, values=main_articles)
    white_start = used_columns + 1
    ws.cell(row=1, column=white_start, value=f"{sheet_label}_white")
    _write_blocks(ws, start_column=white_start, values=white_articles)

    _apply_print_setup(ws)


def _write_blocks(ws, start_column: int, values: Iterable[str]) -> int:
    values = list(values)
    if not values:
        return start_column

    for idx, value in enumerate(values):
        block = idx // ROWS_PER_COLUMN
        row_in_block = (idx % ROWS_PER_COLUMN) + 2
        column = start_column + block
        ws.cell(row=row_in_block, column=column, value=value)

    end_column = start_column + ((len(values) - 1) // ROWS_PER_COLUMN)
    for col in range(start_column, end_column + 1):
        ws.column_dimensions[get_column_letter(col)].width = 25

    return end_column


def _apply_print_setup(ws) -> None:
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_margins = PageMargins(
        left=0.25,
        right=0.25,
        top=0.75,
        bottom=0.75,
        header=0.3,
        footer=0.3,
    )
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1


def _header_map(header_rows) -> dict[str, int]:
    values = next(header_rows, ())
    mapping: dict[str, int] = {}
    for idx, value in enumerate(values):
        normalized = _normalize_header(value)
        if normalized:
            mapping[normalized] = idx
    return mapping


def _normalize_header(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_qty(value) -> int:
    if value is None or str(value).strip() == "":
        return 1
    try:
        parsed = int(float(str(value).replace(",", ".")))
    except ValueError:
        return 1
    return max(parsed, 1)
