@echo off
setlocal EnableDelayedExpansion
title IPMadalena — Instalação
color 0A
chcp 65001 >nul 2>&1

set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

echo.
echo  ============================================================
echo    IPMadalena — Cultos para o Drive
echo    Instalação
echo  ============================================================
echo.

:: ── 1. Verificar / instalar Python ───────────────────────────────────────────
echo  [1/5] Verificando Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo  Python nao encontrado. Tentando instalar via winget...
    winget install --id Python.Python.3.12 --source winget -e ^
        --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo.
        echo  ERRO: Nao foi possivel instalar o Python automaticamente.
        echo  Instale manualmente em: https://python.org/downloads
        echo  Marque "Add Python to PATH" durante a instalacao.
        echo.
        pause
        exit /b 1
    )
    :: Recarrega PATH para encontrar o Python recem instalado
    set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
)
python --version
echo  OK.

:: ── 2. Instalar dependencias Python ──────────────────────────────────────────
echo.
echo  [2/5] Instalando dependencias Python...
python -m pip install --upgrade pip --quiet
python -m pip install ^
    yt-dlp ^
    customtkinter ^
    tkcalendar ^
    google-api-python-client ^
    google-auth-oauthlib ^
    google-auth ^
    plyer ^
    --quiet
if errorlevel 1 (
    echo  ERRO: Falha ao instalar dependencias.
    pause
    exit /b 1
)
echo  OK.

:: ── 3. Baixar ffmpeg ──────────────────────────────────────────────────────────
echo.
echo  [3/5] Configurando ffmpeg...
if exist "%APP_DIR%\ffmpeg\bin\ffmpeg.exe" (
    echo  ffmpeg ja instalado. Pulando.
) else (
    mkdir "%APP_DIR%\ffmpeg\bin" >nul 2>&1
    powershell -ExecutionPolicy Bypass -Command ^
        "$ErrorActionPreference = 'Stop'; " ^
        "$url  = 'https://github.com/BtbN/ffmpeg-builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'; " ^
        "$zip  = '%APP_DIR%\ffmpeg_dl.zip'; " ^
        "$tmp  = '%APP_DIR%\ffmpeg_tmp'; " ^
        "Write-Host '  Baixando ffmpeg...'; " ^
        "Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing; " ^
        "Write-Host '  Extraindo...'; " ^
        "Expand-Archive -Path $zip -DestinationPath $tmp -Force; " ^
        "$exe = Get-ChildItem -Path $tmp -Filter 'ffmpeg.exe' -Recurse | Select-Object -First 1; " ^
        "Copy-Item $exe.FullName '%APP_DIR%\ffmpeg\bin\ffmpeg.exe'; " ^
        "Remove-Item $zip -Force; " ^
        "Remove-Item $tmp -Recurse -Force; " ^
        "Write-Host '  ffmpeg instalado.'"
    if errorlevel 1 (
        echo.
        echo  AVISO: Nao foi possivel baixar o ffmpeg automaticamente.
        echo  Baixe manualmente em https://ffmpeg.org/download.html
        echo  e coloque ffmpeg.exe em: %APP_DIR%\ffmpeg\bin\
        echo.
    ) else (
        echo  OK.
    )
)

:: ── 4. Criar atalho na area de trabalho ──────────────────────────────────────
echo.
echo  [4/5] Criando atalho na area de trabalho...
powershell -ExecutionPolicy Bypass -Command ^
    "$ws      = New-Object -ComObject WScript.Shell; " ^
    "$desktop = [Environment]::GetFolderPath('Desktop'); " ^
    "$lnk     = $ws.CreateShortcut(\"$desktop\IPMadalena.lnk\"); " ^
    "$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)?.Source; " ^
    "if (-not $pythonw) { " ^
    "    $py = (Get-Command python.exe).Source; " ^
    "    $pythonw = $py -replace 'python\.exe','pythonw.exe'; " ^
    "    if (-not (Test-Path $pythonw)) { $pythonw = $py } " ^
    "}; " ^
    "$lnk.TargetPath      = $pythonw; " ^
    "$lnk.Arguments       = \"\`\"%APP_DIR%\app.py\`\"\"; " ^
    "$lnk.WorkingDirectory = '%APP_DIR%'; " ^
    "$lnk.Description     = 'IPMadalena — Cultos para o Drive'; " ^
    "$lnk.Save(); " ^
    "Write-Host '  Atalho criado.'"
if errorlevel 1 (
    echo  AVISO: Nao foi possivel criar o atalho automaticamente.
    echo  Para abrir o app, execute: python "%APP_DIR%\app.py"
)

:: ── 5. Concluido ─────────────────────────────────────────────────────────────
echo.
echo  [5/5] Instalacao concluida!
echo.
echo  Um atalho "IPMadalena" foi criado na sua area de trabalho.
echo  Na primeira execucao o app ira solicitar a configuracao inicial.
echo.
set /p OPEN="  Deseja abrir o aplicativo agora? (S/N): "
if /i "!OPEN!"=="S" (
    start "" pythonw "%APP_DIR%\app.py"
)
echo.
pause
