Unicode true
Target amd64-unicode
!include "MUI2.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"

!ifndef PAYLOAD
  !error "Provide /DPAYLOAD=..."
!endif
!ifndef OUTPUT
  !error "Provide /DOUTPUT=..."
!endif
Name "StadoVet"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\StadoVet"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "StadoVet · Opieka nad stadem"
VIProductVersion "0.1.0.0"
VIAddVersionKey "ProductName" "StadoVet"
VIAddVersionKey "FileDescription" "Instalator StadoVet dla Windows 64-bit"
VIAddVersionKey "FileVersion" "0.1.0"
VIAddVersionKey "LegalCopyright" "StadoVet contributors"

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp
!define MUI_FINISHPAGE_RUN_TEXT "Uruchom StadoVet"
!define MUI_WELCOMEPAGE_TEXT "Program do obsługi gospodarstw i bydła.$\r$\n$\r$\nInstalator zawiera Pythona i zależności. Nie potrzebujesz osobnej instalacji Pythona ani uprawnień administratora.$\r$\n$\r$\nDane są zapisywane oddzielnie w folderze użytkownika."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${PAYLOAD}/LICENSE.txt"
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Polish"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "StadoVet wymaga 64-bitowego systemu Windows 10 lub 11."
    Abort
  ${EndIf}
  SetShellVarContext current
FunctionEnd

Function StopExisting
  IfFileExists "$INSTDIR\runtime\pythonw.exe" 0 done
  IfFileExists "$INSTDIR\launcher.py" 0 done
  ExecWait '"$INSTDIR\runtime\pythonw.exe" "$INSTDIR\launcher.py" --stop' $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Zamknij działający StadoVet przed instalacją."
    Abort
  ${EndIf}
  done:
FunctionEnd

Section "StadoVet" SecMain
  Call StopExisting
  SetOutPath "$INSTDIR"
  File /r "${PAYLOAD}/*"
  WriteUninstaller "$INSTDIR\Odinstaluj.exe"
  CreateDirectory "$SMPROGRAMS\StadoVet"
  CreateShortCut "$DESKTOP\StadoVet.lnk" "$INSTDIR\runtime\pythonw.exe" '"$INSTDIR\launcher.py"' "$INSTDIR\StadoVet.ico"
  CreateShortCut "$SMPROGRAMS\StadoVet\StadoVet.lnk" "$INSTDIR\runtime\pythonw.exe" '"$INSTDIR\launcher.py"' "$INSTDIR\StadoVet.ico"
  CreateShortCut "$SMPROGRAMS\StadoVet\Zatrzymaj StadoVet.lnk" "$INSTDIR\runtime\pythonw.exe" '"$INSTDIR\launcher.py" --stop' "$INSTDIR\StadoVet.ico"
  CreateShortCut "$SMPROGRAMS\StadoVet\Instrukcja.lnk" "$INSTDIR\INSTRUKCJA.txt"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\StadoVet" "DisplayName" "StadoVet"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\StadoVet" "DisplayVersion" "0.1.0"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\StadoVet" "UninstallString" '$\"$INSTDIR\Odinstaluj.exe$\"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\StadoVet" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\StadoVet" "DisplayIcon" "$INSTDIR\StadoVet.ico"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\StadoVet" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\StadoVet" "NoRepair" 1
SectionEnd

Function LaunchApp
  Exec '"$INSTDIR\runtime\pythonw.exe" "$INSTDIR\launcher.py"'
FunctionEnd

Function un.onInit
  SetShellVarContext current
  ExecWait '"$INSTDIR\runtime\pythonw.exe" "$INSTDIR\launcher.py" --stop' $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Zamknij działający StadoVet przed odinstalowaniem."
    Abort
  ${EndIf}
FunctionEnd

Section "Uninstall"
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\app"
  Delete "$INSTDIR\launcher.py"
  Delete "$INSTDIR\StadoVet.ico"
  Delete "$INSTDIR\INSTRUKCJA.txt"
  Delete "$INSTDIR\LICENSE.txt"
  Delete "$INSTDIR\BUILD-MANIFEST.json"
  Delete "$INSTDIR\Odinstaluj.exe"
  RMDir "$INSTDIR"
  Delete "$DESKTOP\StadoVet.lnk"
  Delete "$SMPROGRAMS\StadoVet\StadoVet.lnk"
  Delete "$SMPROGRAMS\StadoVet\Zatrzymaj StadoVet.lnk"
  Delete "$SMPROGRAMS\StadoVet\Instrukcja.lnk"
  RMDir "$SMPROGRAMS\StadoVet"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\StadoVet"
  ; Intentionally retain $LOCALAPPDATA\StadoVet, including the real database and logs.
SectionEnd
