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

REM 3. Копирование SumatraPDF (если есть)
echo [3/4] Поиск SumatraPDF...
set SUMATRA=
if exist "..\SumatraPDF.exe" set SUMATRA=..\SumatraPDF.exe
if exist "SumatraPDF.exe" set SUMATRA=SumatraPDF.exe
if defined SUMATRA (
    copy /Y "%SUMATRA%" dist\SumatraPDF.exe >nul
    echo   SumatraPDF скопирован в dist\
) else (
    echo   SumatraPDF не найден. Положите SumatraPDF.exe в dist\ или в корень FBS.
    echo   Установщик соберётся без него — пользователь может установить отдельно.
)

REM 4. Сборка установщика (Inno Setup)
echo [4/4] Сборка установщика...
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
