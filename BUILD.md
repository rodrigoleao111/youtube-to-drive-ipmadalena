# Instruções de Build — IPMadalena

## Pré-requisitos

| Ferramenta | Versão | Local padrão |
|---|---|---|
| Python | 3.12 | `C:\Users\rasantos\AppData\Local\Programs\Python\Python312\python.exe` |
| PyInstaller | qualquer | instalado via pip |
| Inno Setup 6 | 6.x | `C:\Users\rasantos\AppData\Local\Programs\Inno Setup 6\ISCC.exe` |
| yt-dlp standalone | qualquer | `.\yt-dlp.exe` (na raiz do projeto) |
| ffmpeg | qualquer | `.\ffmpeg\bin\ffmpeg.exe` (na raiz do projeto) |

> **yt-dlp.exe e ffmpeg devem estar presentes na raiz do projeto antes do build.**
> Use `build_installer.bat` para baixá-los automaticamente, ou coloque manualmente.

---

## Regra de ouro: um processo ISCC por vez

O Inno Setup cria o arquivo de saída `dist\IPMadalena_Setup.exe` durante a
compilação. Se um segundo processo ISCC for iniciado enquanto o primeiro ainda
está rodando — ou se o arquivo anterior ainda estiver aberto por outro processo
(Explorer, antivírus, instalador em execução) — o build falhará com:

```
Error 32: O arquivo já está sendo usado por outro processo.
Compile aborted.
```

**Antes de qualquer build, garanta que:**
1. Nenhum processo ISCC está ativo: `taskkill /IM ISCC.exe /F`
2. O instalador anterior não está aberto/executando
3. `dist\IPMadalena_Setup.exe` pode ser excluído manualmente se necessário

---

## Passo a passo manual

### 1. Limpar artefatos anteriores

```powershell
Remove-Item dist\IPMadalena_Setup.exe -Force -ErrorAction SilentlyContinue
Remove-Item dist\IPMadalena -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item build -Recurse -Force -ErrorAction SilentlyContinue
```

### 2. Rodar os testes (obrigatório antes de qualquer release)

```powershell
python -m pytest tests/
```

Todos os testes **devem** passar (atualmente 393/393). Nunca faça build com
testes falhando.

### 3. PyInstaller — gerar `dist\IPMadalena\`

```powershell
python -m PyInstaller build_app.spec --noconfirm --clean
```

Saída esperada na última linha:
```
INFO: Build complete! The results are available in: ...\dist
```

### 4. Inno Setup — gerar `dist\IPMadalena_Setup.exe`

```powershell
& "C:\Users\rasantos\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

Saída esperada na última linha:
```
Successful compile (x.xx sec). Resulting Setup program filename is:
C:\Users\rasantos\youtube_to_drive\dist\IPMadalena_Setup.exe
```

---

## Script automatizado: `build_installer.bat`

O arquivo `build_installer.bat` executa todos os passos acima em sequência,
incluindo o download do `yt-dlp.exe` standalone. Para usar:

```bat
build_installer.bat
```

> **Atenção:** o `.bat` assume que não há outro processo ISCC rodando.
> Se o build anterior foi interrompido, execute `taskkill /IM ISCC.exe /F`
> antes de chamar o `.bat`.

---

## Troubleshooting

### `Error 32: O arquivo já está sendo usado por outro processo`

O `IPMadalena_Setup.exe` está travado. Soluções:

```powershell
# 1. Mata todos os processos ISCC
taskkill /IM ISCC.exe /F

# 2. Remove o arquivo (se conseguir)
del dist\IPMadalena_Setup.exe /F

# 3. Tenta novamente
& "C:\Users\rasantos\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

Se ainda falhar, o Windows Explorer ou o antivírus pode estar segurando o
arquivo. Feche o Explorer, desative temporariamente a proteção em tempo real,
ou reinicie o computador.

### PyInstaller: `ModuleNotFoundError` ou `RecursionError`

```powershell
pip install --upgrade pyinstaller
python -m PyInstaller build_app.spec --noconfirm --clean
```

### yt-dlp.exe não encontrado no bundle

O `build_app.spec` espera `.\yt-dlp.exe` na raiz do projeto. Baixe:

```powershell
Invoke-WebRequest `
  "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" `
  -OutFile "yt-dlp.exe"
```

### Instalador não tem ícone / splash

`icon.ico` deve estar na raiz do projeto. Ele está rastreado no repositório
— verifique com `git status` se foi acidentalmente removido.

---

## Checklist de release

- [ ] `python -m pytest tests/` — 100% verde
- [ ] `CLAUDE.md` atualizado se a arquitetura mudou
- [ ] `README.md` atualizado se o comportamento visível mudou
- [ ] Versão no `installer.iss` (`AppVersion`) atualizada
- [ ] Commit com mensagem convencional (`feat:`, `fix:`, `chore:`, ...)
- [ ] `git push origin main`
- [ ] Build limpo (sem artefatos anteriores)
- [ ] `dist\IPMadalena_Setup.exe` gerado e verificado (tamanho > 100 MB)
- [ ] Instalar e testar manualmente o `.exe` gerado
