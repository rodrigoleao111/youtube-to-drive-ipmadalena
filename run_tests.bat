@echo off
setlocal

set PYTHON=C:\Users\rasantos\AppData\Local\Programs\Python\Python312\python.exe
set "PROJECT=%~dp0"
if "%PROJECT:~-1%"=="\" set "PROJECT=%PROJECT:~0,-1%"

echo.
echo =========================================================
echo  IPMadalena — Suite de Testes
echo =========================================================
echo.

:: Verifica se pytest está instalado
%PYTHON% -m pytest --version >nul 2>&1
if errorlevel 1 (
    echo [!] pytest nao encontrado. Instalando...
    %PYTHON% -m pip install pytest -q
)

:: Executa os testes com saída colorida e relatório de cobertura resumido
%PYTHON% -m pytest "%PROJECT%\tests" -v --tb=short --no-header

echo.
echo =========================================================
if errorlevel 1 (
    echo  Resultado: FALHOU
) else (
    echo  Resultado: PASSOU
)
echo =========================================================
echo.

pause
