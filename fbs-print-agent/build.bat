@echo off
REM Сборка FBS Print Agent в exe
REM Требуется: pip install pyinstaller (рекомендуется 6.x для Python 3.10)

pip install -r requirements.txt
pip install --upgrade pyinstaller

if exist fbs-print-agent.spec del fbs-print-agent.spec
if exist build rmdir /s /q build 2>nul
if exist dist rmdir /s /q dist 2>nul

if exist icon.ico (
    pyinstaller --onefile --noconsole --clean --icon=icon.ico --name=fbs-print-agent main.py
) else (
    pyinstaller --onefile --noconsole --clean --name=fbs-print-agent main.py
)

echo.
echo Готово. exe в dist\fbs-print-agent.exe
echo Скопируйте SumatraPDF.exe в ту же папку или установите в Program Files.
pause
