#define MyAppName "Universal AI Subtitle Translator"
#define MyAppVersion "4.0.3.0"
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

[Registry]
; Register custom URI scheme so the Lua script can launch the app directly (Fallback Protection)
Root: HKCU; Subkey: "Software\Classes\universalsubtitles"; ValueType: string; ValueData: "URL:Universal Subtitles Protocol"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\universalsubtitles"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\universalsubtitles\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey

; ----------------------------------------------------------------------
; FIX FOR MS STORE (Policy 10.1.1.11):
; The [Icons] section has been DELETED entirely. 
; The Microsoft Store wrapper will automatically generate the Start Menu 
; icon for you. Creating one here causes a duplicate and gets the app rejected.
; ----------------------------------------------------------------------

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent