"""
FBS Print Agent — локальный агент для тихой печати этикеток.
HTTP API на localhost, иконка в трее.
"""
import json
import sys
import threading
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
import printer
import print_journal
from config import HOST, PORT, __version__

# Список принтеров через win32print
def _get_printers():
    try:
        import win32print
        return [p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]
    except Exception:
        return []


class PrintRequest(BaseModel):
    data: str  # base64
    printer: str | None = None
    mime: str = "application/pdf"
    print_settings: str | None = None  # noscale | shrink | fit — для этикеток 58/80 мм: noscale (100%)


app = FastAPI(title="FBS Print Agent", version=__version__)

# CORS: localhost + fbs-upakovka.ru (включая поддомены); доп. origins через FBS_PRINT_AGENT_ORIGINS
import os
_origins = os.environ.get("FBS_PRINT_AGENT_ORIGINS", "")
_default_origins = [
    "https://fbs-upakovka.ru",
    "https://www.fbs-upakovka.ru",
    "http://fbs-upakovka.ru",
    "http://www.fbs-upakovka.ru",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
if _origins:
    _allow_origins = [o.strip() for o in _origins.split(",") if o.strip()]
    _allow_origins = list(dict.fromkeys(_allow_origins + _default_origins))
else:
    _allow_origins = _default_origins
# Regex для поддоменов fbs-upakovka.ru (app., dev. и т.д.)
_origin_regex = r"https?://([a-zA-Z0-9-]+\.)*fbs-upakovka\.ru(:\d+)?"
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_origin_regex=_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    printers_list = _get_printers()
    sumatra_path = printer.get_sumatra_path()
    return {
        "ok": True,
        "version": __version__,
        "printers": printers_list,
        "sumatra_path": sumatra_path,
    }


@app.post("/print")
def print_job(req: PrintRequest):
    import base64
    try:
        data = base64.b64decode(req.data)
    except Exception as e:
        print_journal.log_print(None, req.mime or "?", 0, False, str(e))
        raise HTTPException(400, detail=f"Invalid base64: {e}")
    printer_name = req.printer or config.DEFAULT_PRINTER or None
    mime = req.mime or "application/pdf"
    print_settings = req.print_settings if req.print_settings in ("noscale", "shrink", "fit") else None
    ok = printer.print_document(data, mime, printer_name, print_settings=print_settings)
    print_journal.log_print(printer_name, mime, len(data), ok, None if ok else "Print failed")
    if not ok:
        raise HTTPException(500, detail="Print failed")
    return {"ok": True}


@app.get("/print-journal")
def get_print_journal(limit: int = 50):
    """Журнал печати — последние задания (для проверки перехвата)."""
    return {"entries": print_journal.get_entries(limit)}


def run_server():
    """Запуск HTTP-сервера (hypercorn — лучше работает в PyInstaller frozen exe, чем uvicorn)."""
    import asyncio
    from hypercorn.config import Config
    from hypercorn.asyncio import serve

    cfg = Config()
    cfg.bind = [f"{HOST}:{PORT}"]
    cfg.loglevel = "warning"
    try:
        asyncio.run(serve(app, cfg))
    except Exception as e:
        _log_server_error(e)


def _log_server_error(ex: Exception):
    """Записать ошибку сервера в файл (для отладки frozen exe)."""
    import traceback
    log_dir = os.path.join(os.environ.get("APPDATA", ""), "fbs-print-agent")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "server_error.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n--- {__import__('datetime').datetime.now()} ---\n")
        f.write(traceback.format_exc())


def run_tray():
    import pystray
    from PIL import Image

    def create_icon_image():
        # Простая иконка 64x64
        img = Image.new("RGB", (64, 64), color=(66, 133, 244))
        return img

    def on_open(icon, item):
        # Окно статуса с журналом печати
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("FBS Print Agent")
        root.geometry("420x380")
        root.resizable(True, True)

        # Статус
        f_top = tk.Frame(root)
        f_top.pack(fill=tk.X, padx=10, pady=10)
        tk.Label(f_top, text="Агент печати работает", font=("", 12)).pack()
        tk.Label(f_top, text=f"Порт: {PORT}", font=("", 10)).pack()
        printers_list = _get_printers()
        tk.Label(f_top, text=f"Принтеров: {len(printers_list)}", font=("", 10)).pack()
        sp = printer.get_sumatra_path()
        tk.Label(f_top, text=f"SumatraPDF: {sp or 'не найден'}", font=("", 9), fg="gray").pack()

        # Журнал печати
        tk.Label(root, text="Журнал печати (последние задания):", font=("", 10)).pack(anchor=tk.W, padx=10, pady=(10, 0))
        journal_frame = tk.Frame(root)
        journal_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        scrollbar = ttk.Scrollbar(journal_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        journal_text = tk.Text(journal_frame, height=12, wrap=tk.WORD, yscrollcommand=scrollbar.set, font=("Consolas", 9))
        journal_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=journal_text.yview)

        def refresh_journal():
            try:
                entries = print_journal.get_entries(30)
                journal_text.delete("1.0", tk.END)
                if not entries:
                    journal_text.insert(tk.END, "Записей пока нет. Печать через агент появится здесь.")
                else:
                    for e in entries:
                        status = "OK" if e.get("success") else "ОШИБКА"
                        ts = e.get("ts", "")[:19].replace("T", " ")
                        pr = (e.get("printer") or "?")[:25]
                        mime = (e.get("mime") or "?")[:12]
                        sz = e.get("size_bytes", 0)
                        err = e.get("error") or ""
                        line = f"{ts} | {status:6} | {pr:25} | {mime:12} | {sz} байт"
                        if err:
                            line += f" | {err}"
                        journal_text.insert(tk.END, line + "\n")
            except Exception as ex:
                journal_text.delete("1.0", tk.END)
                journal_text.insert(tk.END, f"Не удалось загрузить журнал: {ex}")

        refresh_journal()
        tk.Button(root, text="Обновить журнал", command=refresh_journal).pack(pady=5)

        tk.Button(root, text="Закрыть", command=root.destroy).pack(pady=10)
        root.mainloop()

    def on_quit(icon, item):
        icon.stop()
        sys.exit(0)

    icon = pystray.Icon(
        "fbs-print-agent",
        create_icon_image(),
        "FBS Print Agent",
        menu=pystray.Menu(
            pystray.MenuItem("Открыть", on_open),
            pystray.MenuItem("Выход", on_quit),
        ),
    )
    icon.run()


if __name__ == "__main__":
    # Сервер — в главном потоке (signal.signal работает только там; hypercorn иначе падает)
    # Трей — в фоновом потоке
    tray_thread = threading.Thread(target=run_tray, daemon=True)
    tray_thread.start()
    run_server()
