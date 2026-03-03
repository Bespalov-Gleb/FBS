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
4. Если SumatraPDF не встроен — [скачайте](https://www.sumatrapdfreader.org/download-free-pdf-viewer) и установите в `C:\Program Files\SumatraPDF\`

## Сборка установщика (для разработчиков)

Нужно: Python 3.10+, [Inno Setup 6](https://jrsoftware.org/isdl.php)

```bash
cd fbs-print-agent
build-installer.bat
```

Скрипт:
1. Соберёт exe через PyInstaller
2. Скопирует SumatraPDF.exe в dist\ (если лежит в FBS\ или fbs-print-agent\)
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

Создайте ярлык `fbs-print-agent.exe` и поместите в:
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`

## Переменные окружения

- `FBS_PRINT_AGENT_PORT` — порт (по умолчанию 9199)
- `FBS_PRINT_AGENT_PRINTER` — принтер по умолчанию
- `FBS_PRINT_AGENT_ORIGINS` — **обязательно для продакшена!** CORS origins через запятую. Без этого сайт с другого домена не сможет отправить задание на печать.
  - Пример: `FBS_PRINT_AGENT_ORIGINS=https://fbs-upakovka.ru,https://www.fbs-upakovka.ru`

## API

- `GET /health` — проверка работы, список принтеров
- `POST /print` — печать. Body: `{"data": "base64...", "printer": "Имя", "mime": "application/pdf"}`
