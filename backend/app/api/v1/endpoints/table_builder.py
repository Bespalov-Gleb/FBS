import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import Response

from app.core.dependencies import CurrentUser
from app.models.user import User
from app.services.table_builder_service import build_xlsx_from_paths

router = APIRouter(prefix="/table-builder", tags=["Table Builder"])

_ALLOWED_SUFFIXES = {".xlsx", ".csv"}


@router.post("/build")
async def build_table_xlsx(
    files: list[UploadFile] = File(...),
    current_user: User = CurrentUser,
):
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не выбраны файлы для обработки.",
        )

    invalid_files = [
        f.filename or "unknown"
        for f in files
        if Path(f.filename or "").suffix.lower() not in _ALLOWED_SUFFIXES
    ]
    if invalid_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Поддерживаются только файлы .xlsx и .csv. "
                f"Некорректные файлы: {', '.join(invalid_files)}"
            ),
        )

    with tempfile.TemporaryDirectory(prefix=f"table-builder-{current_user.id}-") as temp_dir:
        input_paths: list[Path] = []
        for idx, uploaded in enumerate(files, start=1):
            name = Path(uploaded.filename or f"file_{idx}.xlsx")
            safe_name = name.name
            temp_path = Path(temp_dir) / f"{idx:03d}_{safe_name}"
            content = await uploaded.read()
            temp_path.write_bytes(content)
            input_paths.append(temp_path)

        try:
            xlsx_bytes, filename, _ = build_xlsx_from_paths(input_paths)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка при формировании таблицы: {exc}",
            ) from exc

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
