; Inno Setup - instalador do POLARIS
; Gera POLARIS-setup-<versao>.exe a partir de dist\POLARIS (saida do PyInstaller).
;
; Uso:
;   1. pyinstaller polaris.spec        (gera dist\POLARIS\)
;   2. abrir este .iss no Inno Setup Compiler e clicar "Compile"
;      (ou: ISCC.exe installer\polaris.iss)
;
; IMPORTANTE: mantenha MyAppVersion igual ao __version__ de version.py.

#define MyAppName "POLARIS"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Ceu Azul Aerodesign - UFSC"
#define MyAppExeName "POLARIS.exe"
#define MyAppURL "https://github.com/CeuAzul/polaris"

[Setup]
AppId={{B8F3A2C1-7E44-4B9A-9C21-POLARISCEUAZUL}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\POLARIS
DefaultGroupName=POLARIS
DisableProgramGroupPage=yes
OutputBaseFilename=POLARIS-setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; PyInstaller ja produz o app; nao exige admin se instalar por usuario:
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na area de trabalho"; GroupDescription: "Atalhos adicionais:"

[Files]
Source: "..\dist\POLARIS\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\POLARIS"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar POLARIS"; Filename: "{uninstallexe}"
Name: "{autodesktop}\POLARIS"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir o POLARIS agora"; Flags: nowait postinstall skipifsilent
