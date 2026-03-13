# Анализ: почему этикетки Ozon не поворачиваются

## Цепочка обработки

1. **Ozon API** → `POST /v2/posting/fbs/package-label` → сырой PDF (bytes)
2. **get_order_label** (orders.py) → выбор пути по `label_print_mode`:
   - `as_is_fit`: `_rotate_pdf(content, 90)` → возврат
   - `standard_58x40_noscale`: `_rotate_pdf(content, ozon_rot)` → `_ozon_fbs_to_standard_label(content, rotate=0)`

## Возможные причины сбоя

### 1. Тихое проглатывание исключения

```python
try:
    if ozon_rot:
        content = _rotate_pdf(content, ozon_rot)
    content = _ozon_fbs_to_standard_label(...)
except Exception as _re:
    logger.warning("Ozon FBS to standard label failed: %s", _re)
return Response(content=content, ...)  # content может остаться НЕповёрнутым!
```

Если `_rotate_pdf` бросает исключение, `content` не перезаписывается — возвращается исходный PDF от Ozon.

### 2. pypdf и PDF Ozon

- PDF от Ozon может содержать `/Rotate` в метаданных страницы.
- `pdf2image` рендерит с учётом Rotate — размеры/ориентация могут быть неочевидными.
- `page.rotate(90)` в pypdf меняет `/Rotate`; при уже повёрнутой странице результат может быть неожиданным (накопление поворотов).

### 3. Поворот отключён в _ozon_fbs_to_standard_label

Сейчас в noscale передаётся `rotate=0`:

```python
content = _ozon_fbs_to_standard_label(..., rotate=0, ...)
```

Из-за этого блок PIL-поворота не выполняется:

```python
if rotate and rotate % 90 == 0:  # 0 — falsy, условие ложно
    img = img.rotate(rotate, expand=True)
```

Поворот изображения через PIL никогда не вызывается.

### 4. Двойная зависимость от pypdf

Мы полностью полагаемся на `_rotate_pdf` (pypdf). Если он не срабатывает из‑за формата Ozon — визуальный поворот не происходит.

## Реализованные исправления (13.03.2026)

1. **pdf2image `use_pdftocairo=True`** — pdftocairo корректнее обрабатывает PDF с `/Rotate` в метаданных. Fallback на обычный convert при ошибке.

2. **PIL `transpose(ROTATE_270)`** вместо `rotate(-90)` — для 90° по часовой, более предсказуемое поведение.

3. **Поворот только при portrait (ih > iw)** — если изображение уже альбомное, не крутим (не портим).

4. **Кроп белой рамки** — фон для diff задан явно `(255,255,255)`, а не через getpixel(0,0).

5. **Передача `ozon_rot`** из настроек диспетчера в `_ozon_fbs_to_standard_label`.
