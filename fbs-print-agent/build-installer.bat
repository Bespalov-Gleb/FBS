@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ========================================
echo   Сборка FBS Print Agent — установщик
echo ========================================
echo.

REM 1. Установка зависимостей
echo [1/4] Установка зависимостей...
pip install -q -r requirements.txt
pip install -q --upgrade pyinstaller
if errorlevel 1 (
    echo Ошибка: не удалось установить зависимости
    pause
    exit /b 1
)

REM 2. Сборка exe (spec с hiddenimports для uvicorn — иначе HTTP-сервер не стартует в frozen exe)
echo [2/4] Сборка exe...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller --clean fbs-print-agent.spec
if errorlevel 1 (
    echo Ошибка: не удалось собрать exe
    pause
    exit /b 1
)

REM 3. Копирование SumatraPDF — только ПОРТАТИВНАЯ версия (ZIP), не installer!
echo [3/4] Поиск SumatraPDF...
if exist "..\SumatraPDF.exe" (
    copy /Y "..\SumatraPDF.exe" dist\SumatraPDF.exe >nul
    goto sumatra_done
)
if exist "SumatraPDF.exe" (
    copy /Y "SumatraPDF.exe" dist\SumatraPDF.exe >nul
    goto sumatra_done
)
if exist "SumatraPDF-3.5.2-64.zip" (
    powershell -Command "Expand-Archive -Path 'SumatraPDF-3.5.2-64.zip' -DestinationPath 'dist\sumatra_extract' -Force"
    if exist "dist\sumatra_extract\SumatraPDF.exe" (
        copy /Y "dist\sumatra_extract\SumatraPDF.exe" dist\SumatraPDF.exe >nul
    ) else if exist "dist\sumatra_extract\SumatraPDF-3.5.2-64.exe" (
        copy /Y "dist\sumatra_extract\SumatraPDF-3.5.2-64.exe" dist\SumatraPDF.exe >nul
    )
    if exist "dist\SumatraPDF.exe" (
        rmdir /s /q "dist\sumatra_extract" 2>nul
        goto sumatra_done
    )
)
if exist "..\SumatraPDF-3.5.2-64.zip" (
    powershell -Command "Expand-Archive -Path '..\SumatraPDF-3.5.2-64.zip' -DestinationPath 'dist\sumatra_extract' -Force"
    if exist "dist\sumatra_extract\SumatraPDF.exe" (
        copy /Y "dist\sumatra_extract\SumatraPDF.exe" dist\SumatraPDF.exe >nul
    ) else if exist "dist\sumatra_extract\SumatraPDF-3.5.2-64.exe" (
        copy /Y "dist\sumatra_extract\SumatraPDF-3.5.2-64.exe" dist\SumatraPDF.exe >nul
    )
    if exist "dist\SumatraPDF.exe" (
        rmdir /s /q "dist\sumatra_extract" 2>nul
        goto sumatra_done
    )
)
echo   ОШИБКА: SumatraPDF не найден.
echo   Скачайте ПОРТАТИВНУЮ версию: SumatraPDF-3.5.2-64.zip
echo   https://www.sumatrapdfreader.org/download-free-pdf-viewer
echo   Положите ZIP в папку fbs-print-agent и перезапустите сборку.
pause
exit /b 1
:sumatra_done
echo   SumatraPDF скопирован в dist\

REM 4. Копирование Poppler (pdftocairo + DLL) в dist\poppler\bin
echo [4/5] Поиск Poppler (pdftocairo)...
if exist "dist\poppler" rmdir /s /q "dist\poppler" 2>nul
set POPPLER_BIN=
if exist "poppler\bin\pdftocairo.exe" set POPPLER_BIN=poppler\bin
if not defined POPPLER_BIN if exist "poppler-25.12.0\Library\bin\pdftocairo.exe" set POPPLER_BIN=poppler-25.12.0\Library\bin
if not defined POPPLER_BIN if exist "..\fbs-print-agent\poppler\bin\pdftocairo.exe" set POPPLER_BIN=..\fbs-print-agent\poppler\bin
if not defined POPPLER_BIN if exist "..\fbs-print-agent\poppler-25.12.0\Library\bin\pdftocairo.exe" set POPPLER_BIN=..\fbs-print-agent\poppler-25.12.0\Library\bin

if defined POPPLER_BIN (
    mkdir "dist\poppler\bin" >nul 2>&1
    xcopy /E /I /Y "%POPPLER_BIN%\*" "dist\poppler\bin\" >nul
    if exist "dist\poppler\bin\pdftocairo.exe" (
        echo   Poppler скопирован в dist\poppler\bin\
    ) else (
        echo   ПРЕДУПРЕЖДЕНИЕ: Poppler найден, но pdftocairo.exe не скопировался.
    )
) else (
    echo   ПРЕДУПРЕЖДЕНИЕ: Poppler ^(pdftocairo.exe^) не найден.
    echo   GDI-ветка печати PDF будет отключена, агент откатится на SumatraPDF.
    echo   Ожидаемые пути:
    echo     - fbs-print-agent\poppler\bin\pdftocairo.exe
    echo     - fbs-print-agent\poppler-25.12.0\Library\bin\pdftocairo.exe
)

REM 5. Сборка установщика (Inno Setup)
echo [5/5] Сборка установщика...
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set ISCC=C:\Program Files\Inno Setup 6\ISCC.exe
where iscc >nul 2>&1 && set ISCC=iscc

if defined ISCC (
    "%ISCC%" installer.iss
    if errorlevel 1 (
        echo Ошибка компиляции Inno Setup
        pause
        exit /b 1
    )
    echo.
    echo Готово! Установщик: output\FBS-Print-Agent-Setup-0.1.0.exe
) else (
    echo.
    echo Inno Setup 6 не найден. Установите: https://jrsoftware.org/isdl.php
    echo Затем откройте installer.iss в Inno Setup и нажмите Compile.
    echo.
    echo Или добавьте ISCC в PATH и запустите: iscc installer.iss
)

echo.
pause
