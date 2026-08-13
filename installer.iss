; Inno Setup Script — IPMadalena Cultos para o Drive
; Requer: PyInstaller já executado (saída em dist\IPMadalena\)
; Gera:   dist\IPMadalena_Setup.exe

#define AppName      "IPMadalena — Cultos para o Drive"
#define AppShortName "IPMadalena"
#define AppVersion   "3.5.2"
#define AppPublisher "Igreja Presbiteriana de Madalena"
#define AppExeName   "IPMadalena.exe"

[Setup]
AppId={{A3F72B1C-4D8E-4F2A-9C3B-1E7D5A8F0B92}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppShortName}
DefaultGroupName={#AppShortName}
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=IPMadalena_Setup
SetupIconFile=icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=120
DisableWelcomePage=no
DisableProgramGroupPage=auto
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; \
    GroupDescription: "Atalhos adicionais:"; Flags: unchecked

[Files]
; Bundle gerado pelo PyInstaller
Source: "dist\IPMadalena\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppShortName}";      Filename: "{app}\{#AppExeName}"
Name: "{group}\Desinstalar {#AppShortName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppShortName}"; Filename: "{app}\{#AppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "Iniciar {#AppShortName} agora"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove pastas geradas em runtime (downloads, logs, config) se o usuário confirmar
Type: filesandordirs; Name: "{app}\downloads"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
// Avisa o usuário que credentials/ e assets/vinhetas/ não são removidas na desinstalação
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then begin
    MsgBox(
      'Desinstalação concluída.' + #13#10 + #13#10 +
      'Foram mantidas as suas credenciais Google e o login do Spotify' + #13#10 +
      '(pasta "credentials") e as vinhetas salvas (pasta' + #13#10 +
      '"assets\vinhetas"). Remova-as manualmente se desejar.',
      mbInformation, MB_OK
    );
  end;
end;
