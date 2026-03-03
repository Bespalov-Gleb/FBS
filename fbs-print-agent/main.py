"""
FBS Print Agent — локальный агент для тихой печати этикеток.
HTTP API на localhost, иконка в трее.
"""
import sys
import threading
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from uvicorn import Config, Server

import config
import printer
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


app = FastAPI(title="FBS Print Agent", version=__version__)

# CORS: localhost с любым портом; для продакшена задать FBS_PRINT_AGENT_ORIGINS
import os
_origins = os.environ.get("FBS_PRINT_AGENT_ORIGINS", "")
if _origins:
    _allow_origins = [o.strip() for o in _origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health")
def health():
    printers_list = _get_printers()
    return {"ok": True, "version": __version__, "printers": printers_list}


@app.post("/print")
def print_job(req: PrintRequest):
    import base64
    try:
        data = base64.b64decode(req.data)
    except Exception as e:
        raise HTTPException(400, detail=f"Invalid base64: {e}")
    printer_name = req.printer or config.DEFAULT_PRINTER or None
    ok = printer.print_document(data, req.mime or "application/pdf", printer_name)
    if not ok:
        raise HTTPException(500, detail="Print failed")
    return {"ok": True}


def run_server():
    cfg = Config(app, host=HOST, port=PORT, log_level="warning")
    server = Server(cfg)
    import asyncio
    asyncio.run(server.serve())


def run_tray():
    import pystray
    from PIL import Image

    def create_icon_image():
        # Простая иконка 64x64
        img = Image.new("RGB", (64, 64), color=(66, 133, 244))
        return img

    def on_open(icon, item):
        # Мини-окно статуса
        import tkinter as tk
        root = tk.Tk()
        root.title("FBS Print Agent")
        root.geometry("300x200")
        root.resizable(False, False)
        tk.Label(root, text="Агент печати работает", font=("", 12)).pack(pady=20)
        tk.Label(root, text=f"Порт: {PORT}", font=("", 10)).pack()
        printers_list = _get_printers()
        tk.Label(root, text=f"Принтеров: {len(printers_list)}", font=("", 10)).pack()
        tk.Button(root, text="Закрыть", command=root.destroy).pack(pady=20)
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
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    run_tray()
