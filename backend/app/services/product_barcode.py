"""Выбор товарного штрихкода для печати.

Новые коды Честного знака начинаются с нуля. Если такого нет — печатаем запасной
(для Ozon это OZN+SKU, для WB и Яндекса — первый оставшийся код).
"""
from typing import Optional


def choose_product_barcode(
    codes: list[str] | None,
    fallback: Optional[str] = None,
) -> Optional[str]:
    """Первый код с нуля, иначе fallback, иначе первый непустой код."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in codes or []:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    zeros = [code for code in cleaned if code.startswith("0")]
    if zeros:
        return zeros[0]
    fb = str(fallback or "").strip()
    if fb:
        return fb
    return cleaned[0] if cleaned else None
