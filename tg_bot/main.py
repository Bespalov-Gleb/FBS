from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from excel_processor import process_files

logging.basicConfig(level=logging.INFO)

BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"

# user_id -> list of uploaded file paths
USER_FILES: dict[int, list[Path]] = defaultdict(list)


def _get_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN")
    return token


def _sanitize_filename(name: str) -> str:
    keep = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_", ".", " "):
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep).strip() or "file.xlsx"


async def start_handler(message: Message) -> None:
    await message.answer(
        "Отправьте Excel-файлы Ozon/WB одним или несколькими сообщениями.\n"
        "После загрузки введите /build для формирования итоговой таблицы.\n"
        "Команда /clear очищает текущий набор файлов."
    )


async def clear_handler(message: Message) -> None:
    user_id = message.from_user.id
    files = USER_FILES.get(user_id, [])
    for p in files:
        if p.exists():
            p.unlink()
    USER_FILES[user_id] = []
    await message.answer("Список загруженных файлов очищен.")


async def doc_handler(message: Message, bot: Bot) -> None:
    if not message.document:
        return

    filename = _sanitize_filename(message.document.file_name or "file.xlsx")
    user_dir = UPLOADS_DIR / str(message.from_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    destination = user_dir / filename

    if destination.exists():
        stem = destination.stem
        suffix = destination.suffix
        counter = 1
        while destination.exists():
            destination = user_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    await bot.download(message.document, destination=destination)
    USER_FILES[message.from_user.id].append(destination)
    await message.answer(f"Файл принят: {destination.name}")


async def build_handler(message: Message) -> None:
    user_id = message.from_user.id
    files = USER_FILES.get(user_id, [])
    if not files:
        await message.answer("Нет загруженных файлов. Сначала отправьте Excel, затем /build.")
        return

    await message.answer("Обрабатываю файлы, это может занять до минуты...")

    user_output_dir = OUTPUTS_DIR / str(user_id)
    try:
        output_file, counts = process_files(files, user_output_dir)
    except Exception as exc:
        await message.answer(f"Ошибка при обработке: {exc}")
        return

    await message.answer_document(
        FSInputFile(output_file),
        caption=f"Готово. Ozon: {counts['ozon']}, WB: {counts['wb']}",
    )


async def main() -> None:
    bot = Bot(token=_get_token())
    dp = Dispatcher()

    dp.message.register(start_handler, Command("start"))
    dp.message.register(clear_handler, Command("clear"))
    dp.message.register(build_handler, Command("build"))
    dp.message.register(doc_handler, F.document)

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
