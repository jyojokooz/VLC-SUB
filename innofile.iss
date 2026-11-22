#define MyAppName "Universal AI Subtitle Translator"
#define MyAppVersion "4.0.4.0"
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
; NOTE: A Start Menu shortcut IS required here. MSIX Packaging Tool
; detects the app's entry point (Package/Applications element in the
; manifest) by watching for a shortcut created during install. Without
; one, the .msix ends up with no <Application> element at all, which
; Partner Center rejects with "doesn't contain any Application elements
; in the app manifest file." The earlier removal of this section was
; based on a Visual Studio/UWP assumption that doesn't apply to a
; manually-converted desktop app like this one.
; ----------------------------------------------------------------------
[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent