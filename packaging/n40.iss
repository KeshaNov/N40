; Inno Setup: установщик N40
; Сборка: iscc /DAppVersion=0.1.0 packaging\n40.iss   (после PyInstaller)

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{7C1F3E2A-4B0D-4C1E-9E61-3A5D40C0FFEE}
AppName=N40
AppVersion={#AppVersion}
AppPublisher=N40
AppPublisherURL=https://github.com/KeshaNov/N40
AppUpdatesURL=https://github.com/KeshaNov/N40/releases
DefaultDirName={autopf}\N40
DefaultGroupName=N40
OutputDir=..\dist
OutputBaseFilename=N40-Setup-{#AppVersion}
SetupIconFile=n40.ico
UninstallDisplayIcon={app}\N40.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assoc"; Description: "Открывать файлы проектов .n40 в N40"; GroupDescription: "Ассоциации:"

[Files]
Source: "..\dist\N40.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\N40"; Filename: "{app}\N40.exe"
Name: "{group}\Удалить N40"; Filename: "{uninstallexe}"
Name: "{autodesktop}\N40"; Filename: "{app}\N40.exe"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.n40"; ValueType: string; ValueData: "N40.Project"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\N40.Project"; ValueType: string; ValueData: "Проект N40"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\N40.Project\DefaultIcon"; ValueType: string; ValueData: "{app}\N40.exe,0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\N40.Project\shell\open\command"; ValueType: string; ValueData: """{app}\N40.exe"" ""%1"""; Tasks: assoc

[Run]
Filename: "{app}\N40.exe"; Description: "{cm:LaunchProgram,N40}"; Flags: nowait postinstall skipifsilent
