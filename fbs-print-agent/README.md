# FBS Print Agent

Локальный агент для тихой печати этикеток FBS без диалогов браузера.

## Требования

- Windows
- Python 3.10+ (только для разработки и сборки)
- [SumatraPDF](https://www.sumatrapdfreader.org/download-free-pdf-viewer) — для печати PDF и изображений

## Установка для пользователей (рекомендуется)

1. Скачайте **FBS-Print-Agent-Setup-0.1.0.exe** (установщик)
2. Запустите установщик и следуйте шагам
3. При установке можно выбрать:
   - значок на рабочем столе
   - автозапуск при входе в Windows
4. **Запуск:** используйте ярлык «FBS Print Agent» (меню Пуск или рабочий стол). Не запускайте `fbs-print-agent.exe` напрямую — ярлык задаёт привязку к сайту fbs-upakovka.ru.
5. **Если печать не работает** — нужна **портативная** версия SumatraPDF (не установщик). Скачайте [64-bit portable](https://www.sumatrapdfreader.org/download-free-pdf-viewer) (ZIP), извлеките `SumatraPDF.exe` и скопируйте в `%APPDATA%\fbs-print-agent\`. Либо пересоберите установщик, положив `SumatraPDF.exe` в папку `fbs-print-agent` перед сборкой.

## Сборка установщика (для разработчиков)

Нужно: Python 3.10+, [Inno Setup 6](https://jrsoftware.org/isdl.php)

```bash
cd fbs-print-agent
build-installer.bat
```

Скрипт:
1. Соберёт exe через PyInstaller
2. Скопирует SumatraPDF.exe в dist\ — ищет в таком порядке:
   - `SumatraPDF.exe` в FBS\ или fbs-print-agent\
   - `SumatraPDF-3.5.2-64.zip` в fbs-print-agent\ или FBS\ (извлечёт exe из архива)
   **Обязательно портативная версия** (ZIP, не installer), иначе «corrupted installation»
3. Создаст установщик через Inno Setup

Готовый установщик: `output\FBS-Print-Agent-Setup-0.1.0.exe`

## Запуск (разработка)

```bash
cd fbs-print-agent
pip install -r requirements.txt
python main.py
```

Агент запустится в трее. HTTP API: `http://127.0.0.1:9199`

## Сборка только exe (без установщика)

```bash
build.bat
```

exe будет в `dist/fbs-print-agent.exe`. Скопируйте `SumatraPDF.exe` рядом с exe или установите SumatraPDF в систему.

## Ошибка PyInstaller «IndexError: tuple index out of range»

При Python 3.10 возможна ошибка в фазе анализа. Решения:
1. Обновите PyInstaller: `pip install --upgrade pyinstaller` (нужна версия 6.x)
2. Обновите Python до 3.10.3+ (исправлен баг в CPython)
3. Запустите сборку заново — скрипт удаляет старые build/spec

## Автозапуск (ручная настройка)

При установке через установщик можно включить «Запускать при входе в Windows».  
Если настраиваете вручную — создайте ярлык на `run-agent.vbs` (из папки установки) и поместите в:
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`

## Переменные окружения

- `FBS_PRINT_AGENT_PORT` — порт (по умолчанию 9199)
- `FBS_PRINT_AGENT_PRINTER` — принтер по умолчанию
- `FBS_PRINT_AGENT_ORIGINS` — CORS origins через запятую. Без этого сайт fbs-upakovka.ru не сможет отправить задание на печать. При запуске через ярлык установщика задаётся автоматически.

## API

- `GET /health` — проверка работы, список принтеров
- `POST /print` — печать. Body: `{"data": "base64...", "printer": "Имя", "mime": "application/pdf"}`
- `GET /print-journal` — журнал печати (последние задания, для проверки перехвата)

## Журнал печати

При каждом задании на печать агент записывает запись в журнал. Откройте окно агента (правый клик по иконке в трее → «Открыть») — там отображаются последние задания с датой, принтером, типом и результатом. Журнал хранится в `%APPDATA%\fbs-print-agent\print_journal.json`.

**Ошибки печати:** при сбое печати смотрите `%APPDATA%\fbs-print-agent\print_error.log` — там путь к SumatraPDF, путь к PDF и текст ошибки.

**SumatraPDF вернул 1:** обычно означает «принтер не найден» или «файл не найден». Проверьте:
- задан ли принтер по умолчанию в Windows (Параметры → Устройства → Принтеры);
- или укажите принтер через переменную `FBS_PRINT_AGENT_PRINTER`.
