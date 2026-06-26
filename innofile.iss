#define MyAppName "Universal AI Subtitle Translator"
#define MyAppVersion "4.0.0.0"
#define MyAppPublisher "Joel S Raphael"
#define MyAppExeName "UniversalSubtitles.exe"

[Setup]
; Basic App Info
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\UniversalSubtitleToolkit
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=UniversalSubtitles_Setup
SetupIconFile=logo.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern

; This is very important for MSIX conversion later:
UninstallDisplayIcon={app}\{#MyAppExeName}

; ----------------------------------------------------------------------
; REMOVED [Tasks] section completely.
; We no longer ask for a Desktop icon to prevent Microsoft Store duplication.
; ----------------------------------------------------------------------

[Files]
; IMPORTANT: Make sure this points to your PyInstaller "dist\UniversalSubtitles" folder!
Source: "dist\UniversalSubtitles\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\UniversalSubtitles\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Include the logo for the installer/app icon
Source: "logo.ico"; DestDir: "{app}"; Flags: ignoreversion

; ---> NEW LINE: Install the VLC Lua Extension automatically <---
Source: "universal_subtitles.lua"; DestDir: "{userappdata}\vlc\lua\extensions"; Flags: ignoreversion

[Icons]
; Keep ONLY the Start Menu shortcut. 
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent