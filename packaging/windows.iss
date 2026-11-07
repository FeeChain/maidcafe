#ifndef BuildRoot
  #define BuildRoot "..\dist"
#endif
#ifndef AppVersion
  #error AppVersion must be supplied by packaging/build_desktop.py
#endif
[Setup]
AppId=com.feechain.maidcafe
AppName=maidcafe
AppVersion={#AppVersion}
AppPublisher=FeeChain
AppPublisherURL=https://github.com/FeeChain/maidcafe
DefaultDirName={localappdata}\Programs\maidcafe
DefaultGroupName=maidcafe
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#BuildRoot}
OutputBaseFilename=maidcafe-{#AppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\maidcafe.exe
CloseApplications=yes
SetupLogging=yes
[Files]
Source: "{#BuildRoot}\maidcafe\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\maidcafe"; Filename: "{app}\maidcafe.exe"
Name: "{autodesktop}\maidcafe"; Filename: "{app}\maidcafe.exe"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Run]
Filename: "{app}\maidcafe.exe"; Description: "Open maidcafe"; Flags: nowait postinstall skipifsilent
