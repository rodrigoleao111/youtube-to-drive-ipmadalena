# Configuração — YouTube to Drive

## Pré-requisitos

Execute `setup.bat` para instalar as dependências Python e o ffmpeg automaticamente.

---

## Configuração do Google Drive (feita uma única vez)

Para que o script possa enviar arquivos para o seu Google Drive, você precisa
criar credenciais OAuth no Google Cloud Console. Siga os passos abaixo:

### Passo 1 — Criar projeto no Google Cloud

1. Acesse https://console.cloud.google.com/
2. Clique em **"Selecionar projeto"** → **"Novo projeto"**
3. Dê um nome (ex: `IPMadalena Drive`) e clique em **Criar**

### Passo 2 — Ativar a API do Google Drive

1. No menu lateral, vá em **"APIs e serviços"** → **"Biblioteca"**
2. Pesquise por **"Google Drive API"**
3. Clique em **"Ativar"**

### Passo 3 — Criar credenciais OAuth

1. Vá em **"APIs e serviços"** → **"Credenciais"**
2. Clique em **"+ Criar credenciais"** → **"ID do cliente OAuth"**
3. Se solicitado, configure a **Tela de consentimento OAuth**:
   - Tipo de usuário: **Externo**
   - Preencha apenas os campos obrigatórios (nome do app, e-mail)
   - Em "Escopos", não precisa adicionar nada agora
   - Em "Usuários de teste", adicione seu e-mail: `rasantos@informa.com.br`
   - Salve e volte para Credenciais
4. Em **"Tipo de aplicativo"**, selecione **"App para computador"**
5. Dê um nome (ex: `youtube-to-drive`) e clique em **Criar**
6. Clique em **"Baixar JSON"** (ícone de download)
7. Renomeie o arquivo baixado para **`client_secret.json`**
8. Mova para a pasta:  
   `C:\Users\rasantos\youtube_to_drive\credentials\client_secret.json`

### Passo 4 — Autenticação (primeira execução)

Na primeira vez que rodar o script, um navegador abrirá automaticamente pedindo
que você faça login no Google e autorize o acesso ao Drive.

Após autorizar, o token é salvo em `credentials/token.pkl` e as próximas
execuções não precisarão de login novamente.

---

## Como usar

```bash
cd C:\Users\rasantos\youtube_to_drive
python baixar_audio.py YYYY-MM-DD
```

**Exemplos:**
```bash
python baixar_audio.py 2025-11-10
python baixar_audio.py 2026-01-05
```

### O que o script faz:

1. Busca vídeos publicados na data informada no canal `@IPMadalena/streams`
2. Baixa o áudio no melhor formato e converte para MP3
3. Localiza a pasta do mês correspondente no Drive (ou cria se não existir)
4. Faz upload do(s) MP3(s) para essa pasta
5. Remove o arquivo local após o upload

---

## Estrutura de pastas

```
youtube_to_drive/
├── baixar_audio.py      ← script principal
├── setup.bat            ← instalação de dependências
├── CONFIGURACAO.md      ← este arquivo
├── credentials/
│   ├── client_secret.json   ← você baixa do Google Cloud
│   └── token.pkl            ← gerado automaticamente na 1ª execução
└── downloads/           ← pasta temporária (arquivos são removidos após upload)
```

---

## Solução de problemas

| Problema | Solução |
|----------|---------|
| `yt-dlp: command not found` | Execute `setup.bat` novamente |
| `ffmpeg not found` | Instale o ffmpeg e adicione ao PATH |
| `client_secret.json` não encontrado | Siga o Passo 3 acima |
| Nenhum vídeo encontrado para a data | O canal pode não ter transmitido nessa data, ou a data está errada |
| Erro de autenticação Google | Delete `credentials/token.pkl` e rode o script novamente |
