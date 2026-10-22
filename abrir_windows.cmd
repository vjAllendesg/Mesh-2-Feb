@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m scaffold_feb
) else (
  echo Crea el entorno e instala requirements.txt como indica README.md.
  pause
)
