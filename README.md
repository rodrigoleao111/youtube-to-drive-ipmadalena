# IPMadalena — YouTube to Drive

Automatiza o download do áudio dos cultos do canal [@IPMadalena](https://www.youtube.com/@IPMadalena/streams) no YouTube e o upload para o Google Drive, organizando os arquivos por pasta de mês.

---

## Como usar

### Interface gráfica (recomendado)

```bash
python app.py
```

1. Informe a data do culto (DD/MM/AAAA) ou use o seletor de calendário 📅
2. Clique em **Processar**
3. Selecione os vídeos desejados no popup e clique em **Prosseguir**
4. Acompanhe o progresso pelas barras e pelo log de execução
5. Uma notificação desktop é exibida ao concluir

### Linha de comando

```bash
python baixar_audio.py DD/MM/AAAA
```

**Exemplo:**
```bash
python baixar_audio.py 19/04/2026
```

---

## O que o app faz automaticamente

1. Verifica conexão com a internet e espaço em disco (≥ 500 MB)
2. Limpa arquivos residuais de execuções anteriores
3. Avisa se a data já foi processada antes (pode prosseguir mesmo assim)
4. Atualiza o yt-dlp em background ao iniciar
5. Busca os vídeos publicados na data informada no canal
6. Exibe popup para selecionar quais vídeos processar
7. Baixa o áudio e converte para MP3
8. Localiza a pasta do mês no Drive (ou cria se não existir)
9. Faz o upload com progresso chunk a chunk
10. Remove os arquivos locais após o upload
11. Salva histórico local e exibe notificação desktop

> **Transmissões ao vivo:** o YouTube pode registrar a data de publicação como o dia seguinte ao culto. O script lida com isso automaticamente.

---

## Estrutura do projeto

```
youtube_to_drive/
├── app.py                   ← interface gráfica (customtkinter)
├── baixar_audio.py          ← módulo principal (lógica + CLI)
├── README.md                ← este arquivo
├── CONFIGURACAO.md          ← guia de configuração inicial
├── historico.json           ← datas já processadas (gerado automaticamente)
├── credentials/
│   ├── client_secret.json   ← credenciais OAuth (você baixa do Google Cloud)
│   └── token.pkl            ← token de acesso (gerado automaticamente)
├── downloads/               ← pasta temporária (limpa após cada execução)
├── logs/
│   └── DD-MM-YYYY.log       ← log diário de execução (gerado automaticamente)
└── ffmpeg/
    └── bin/
        └── ffmpeg.exe       ← conversor de áudio
```

---

## Pré-requisitos

- Python 3.10+
- Pacotes Python:
  ```bash
  pip install yt-dlp google-api-python-client google-auth-oauthlib customtkinter tkcalendar plyer
  ```
- ffmpeg (incluído em `ffmpeg/bin/`)
- Credenciais OAuth do Google Drive (veja `CONFIGURACAO.md`)

---

## Configuração inicial

Siga o passo a passo em **`CONFIGURACAO.md`** para:

1. Criar um projeto no Google Cloud Console
2. Ativar a API do Google Drive
3. Gerar o arquivo `credentials/client_secret.json`
4. Fazer a autenticação (abre o navegador uma única vez)

Após a primeira autenticação, o token é salvo em `credentials/token.pkl` e renovado automaticamente. Se o token ficar corrompido, é deletado e a autenticação é refeita automaticamente.

---

## Destino no Google Drive

Os arquivos são enviados para a pasta raiz:
[`https://drive.google.com/drive/folders/1KfsI5zCDL4HZ2pdAWPFfAD3TugplzBez`](https://drive.google.com/drive/folders/1KfsI5zCDL4HZ2pdAWPFfAD3TugplzBez)

Dentro dela, o script localiza automaticamente a subpasta do mês (ex: `Abril-2026`). Se não encontrar, cria automaticamente.

---

## Solução de problemas

| Problema | Solução |
|---|---|
| `yt-dlp: command not found` | Execute `pip install yt-dlp` |
| `client_secret.json` não encontrado | Siga o `CONFIGURACAO.md` |
| Erro de autenticação Google | Delete `credentials/token.pkl` e rode novamente (ou ocorre automaticamente) |
| Nenhum vídeo encontrado para a data | Verifique se o culto foi transmitido nesse dia |
| Upload duplicado | O script detecta arquivos já existentes no Drive e pula automaticamente |
| App abre duas vezes | Somente uma instância é permitida — feche a anterior |
| Sem espaço em disco | O app avisa antes de começar; libere pelo menos 500 MB |
