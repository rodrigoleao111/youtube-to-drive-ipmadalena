@echo off
setlocal
title IPMadalena - Build do Instalador
color 0B

set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

echo.
echo  ============================================================
echo    IPMadalena - Gerando instalador Windows
echo  ============================================================
echo.

:: --- [1/4] Baixar yt-dlp standalone -----------------------------------------
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

:: --- [2/4] Verificar PyInstaller e hooks ----------------------------------------
echo.
echo  [2/4] Verificando PyInstaller e pyinstaller-hooks-contrib...
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo  Instalando PyInstaller...
    pip install pyinstaller pyinstaller-hooks-contrib --quiet
    if errorlevel 1 (
        echo  ERRO: Falha ao instalar PyInstaller.
        pause & exit /b 1
    )
) else (
    :: Garante que hooks-contrib esta presente (necessario para PyQt6/WebEngine)
    pip install pyinstaller-hooks-contrib --quiet
)
echo  OK.

:: --- [3/4] Executar PyInstaller ----------------------------------------------
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

:: --- [4/4] Executar Inno Setup -----------------------------------------------
echo.
echo  [4/4] Gerando instalador com Inno Setup...

:: Procura o Inno Setup em locais comuns (admin e sem-admin)
:: NAO quebrar estas linhas com "^": o caret escapa o fim de linha e o cmd passa
:: a ler os espacos da linha seguinte como um comando ("' ' nao e reconhecido"),
:: deixando ISCC vazio SEMPRE - o script pulava o passo 4 dizendo que o Inno
:: Setup nao estava instalado, mesmo instalado. Uma linha por teste.
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

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
