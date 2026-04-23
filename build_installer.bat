@echo off
setlocal
title IPMadalena — Build do Instalador
color 0B
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

echo.
echo  ============================================================
echo    IPMadalena — Gerando instalador Windows
echo  ============================================================
echo.

:: ── Baixar yt-dlp standalone ─────────────────────────────────────────────────
echo  [1/4] Verificando yt-dlp standalone...
if exist "%APP_DIR%\yt-dlp.exe" (
    echo  Atualizando yt-dlp.exe existente...
    "%APP_DIR%\yt-dlp.exe" -U >nul 2>&1
    echo  OK.
) else (
    echo  Baixando yt-dlp standalone do GitHub...
    powershell -ExecutionPolicy Bypass -Command ^
        "Invoke-WebRequest -Uri 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe' -OutFile '%APP_DIR%\yt-dlp.exe' -UseBasicParsing"
    if errorlevel 1 (
        echo  ERRO: Falha ao baixar yt-dlp.exe.
        pause & exit /b 1
    )
    echo  OK.
)

:: ── Verificar PyInstaller ────────────────────────────────────────────────────
echo.
echo  [2/4] Verificando PyInstaller...
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo  Instalando PyInstaller...
    pip install pyinstaller --quiet
    if errorlevel 1 (
        echo  ERRO: Falha ao instalar PyInstaller.
        pause & exit /b 1
    )
)
echo  OK.

:: ── Executar PyInstaller ─────────────────────────────────────────────────────
echo.
echo  [3/4] Empacotando aplicativo com PyInstaller...
echo  (Isso pode levar alguns minutos)
echo.
cd /d "%APP_DIR%"
pyinstaller build_app.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo  ERRO: PyInstaller falhou. Verifique os erros acima.
    pause & exit /b 1
)
echo.
echo  Bundle gerado em: dist\IPMadalena\

:: ── Executar Inno Setup ──────────────────────────────────────────────────────
echo.
echo  [4/4] Gerando instalador com Inno Setup...

:: Procura o Inno Setup em locais comuns
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" ^
    set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" ^
    set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" ^
    set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if "%ISCC%"=="" (
    echo.
    echo  AVISO: Inno Setup nao encontrado.
    echo  Instale em https://jrsoftware.org/isdl.php e execute novamente,
    echo  ou compile installer.iss manualmente no Inno Setup IDE.
    echo.
    echo  O bundle PyInstaller foi gerado em dist\IPMadalena\
    echo  e pode ser distribuido como pasta comprimida mesmo sem o instalador.
    echo.
    pause & exit /b 0
)

"%ISCC%" "%APP_DIR%\installer.iss"
if errorlevel 1 (
    echo  ERRO: Inno Setup falhou. Verifique os erros acima.
    pause & exit /b 1
)

echo.
echo  ============================================================
echo    Instalador gerado com sucesso!
echo    Arquivo: dist\IPMadalena_Setup.exe
echo  ============================================================
echo.
pause
