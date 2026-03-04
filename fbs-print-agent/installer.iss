; FBS Print Agent — установщик
#define MyAppName "FBS Print Agent"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "FBS"
#define MyAppURL "https://fbs-upakovka.ru"
#define MyAppExeName "fbs-print-agent.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=output
OutputBaseFilename=FBS-Print-Agent-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительные значки:"
Name: "startupicon"; Description: "Запускать при входе в Windows"; GroupDescription: "Дополнительные задачи:"

[Files]
; Основной exe, launcher (vbs — без окна консоли) и SumatraPDF
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "run-agent.vbs"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\SumatraPDF.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
; Ярлыки запускают run-agent.vbs через wscript (обход ошибки 193 на некоторых системах)
Name: "{group}\{#MyAppName}"; Filename: "wscript.exe"; Parameters: "//B ""{app}\run-agent.vbs"""; WorkingDir: "{app}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "wscript.exe"; Parameters: "//B ""{app}\run-agent.vbs"""; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "wscript.exe"; Parameters: "//B ""{app}\run-agent.vbs"""; WorkingDir: "{app}"; Description: "Запустить агент печати"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('startupicon') then
    begin
      // Добавить в автозагрузку — run-agent.vbs задаёт CORS для сайта
      RegWriteStringValue(HKEY_CURRENT_USER,
        'Software\Microsoft\Windows\CurrentVersion\Run',
        'FBS Print Agent',
        ExpandConstant('wscript.exe //B "{app}\run-agent.vbs"'));
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if RegValueExists(HKEY_CURRENT_USER,
      'Software\Microsoft\Windows\CurrentVersion\Run',
      'FBS Print Agent') then
      RegDeleteValue(HKEY_CURRENT_USER,
        'Software\Microsoft\Windows\CurrentVersion\Run',
        'FBS Print Agent');
end;
