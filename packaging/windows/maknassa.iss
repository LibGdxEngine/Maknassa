; Inno Setup script — wraps the PyInstaller one-folder build (dist\maknassa\)
; into a single double-click installer: Maknassa-Setup.exe.
;
; Build the bundle first (packaging\build.ps1), then compile this with Inno Setup:
;     iscc packaging\windows\maknassa.iss
; Output: dist\Maknassa-Setup.exe  (version-less name -> stable "latest" download link)

#define MyAppName "Maknassa"
#define MyAppVersion "1.0.0"
#define MyAppExeName "maknassa-gui.exe"
#define MyAppPublisher "Maknassa contributors"

[Setup]
AppId={{B2B1C3D4-5E6F-4A7B-8C9D-0E1F2A3B4C5D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Default to a per-user install (no admin prompt) — smoother for non-technical users
; and avoids UAC/permission issues writing the ~150MB Chromium bundle into Program
; Files. With lowest privileges {autopf} resolves to %LOCALAPPDATA%\Programs. A user
; can still opt into an all-users install via the dialog (PrivilegesRequiredOverrides).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#SourcePath}\..\..\dist
OutputBaseFilename=Maknassa-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#SourcePath}\..\icons\maknassa.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The entire PyInstaller one-folder output (maknassa-gui.exe + _internal\, incl. bundled Chromium).
Source: "{#SourcePath}\..\..\dist\maknassa\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
