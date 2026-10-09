; MdNote installer. Prepare the precise inventory before compiling:
; python scripts/prepare_installer.py
; makensis installer/setup.nsi

Unicode True
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "WordFunc.nsh"
!addincludedir "${__FILEDIR__}"
!include "generated-files.nsh"

Name "MdNote"
OutFile "..\MdNote-Setup-${APP_VERSION}.exe"
InstallDir "$PROGRAMFILES64\MdNote"
RequestExecutionLevel admin
VIProductVersion "${APP_PRODUCT_VERSION}"
VIAddVersionKey /LANG=2052 "ProductName" "MdNote"
VIAddVersionKey /LANG=2052 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "FileDescription" "MdNote 安装程序"
VIAddVersionKey /LANG=2052 "LegalCopyright" "MdNote"
ShowInstDetails hide
ShowUninstDetails hide

!define MUI_ABORTWARNING
!define MUI_ICON "..\mdnote\resources\icon.ico"
!define MUI_UNICON "..\mdnote\resources\icon.ico"
; Leaving the directory page must pass the dedicated-directory check.
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE ValidateInstallDir
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

; Refuse replacement/removal while the application is running. Never force-kill
; an editor: the user must save documents and close it before retrying.
!macro DEFINE_CLOSED_GUARD FUNCTION_NAME
Function ${FUNCTION_NAME}
retry:
  System::Call 'kernel32::WaitNamedPipeW(w "\\.\pipe\mdnote-py-single-instance", i 0) i .r0 ?e'
  Pop $1
  StrCmp $0 0 0 running
  IntCmp $1 2 closed
  IntCmp $1 3 closed
running:
  IfSilent stop
  MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "请先保存文件并退出 MdNote，再点击重试。安装程序不会强制关闭编辑器。" IDRETRY retry
stop:
  SetErrorLevel 2
  Quit
closed:
FunctionEnd
!macroend
!insertmacro DEFINE_CLOSED_GUARD EnsureMdNoteClosed
!insertmacro DEFINE_CLOSED_GUARD un.EnsureMdNoteClosed

; Only install into a dedicated folder: non-existent/empty, or an existing
; MdNote installation being upgraded. A folder containing other files is
; refused; uninstall likewise only removes the application inventory.
Function ValidateInstallDir
  Push $R0
  Push $R1
  ; Refuse filesystem roots (e.g. C:\).
  ${GetRoot} "$INSTDIR" $R0
  StrCmp $R0 "$INSTDIR" VID_Dirty 0
  ; Existing MdNote installs may be upgraded in place.
  ClearErrors
  IfFileExists "$INSTDIR\MdNote.exe" VID_Valid 0
  IfFileExists "$INSTDIR\Uninstall.exe" VID_Valid 0
  ; Otherwise the directory must be empty (or not yet created).
  FindFirst $R0 $R1 "$INSTDIR\*"
  StrCmp $R0 "" VID_Valid
VID_Scan:
  StrCmp $R1 "." VID_Next
  StrCmp $R1 ".." VID_Next
  FindClose $R0
  Goto VID_Dirty
VID_Next:
  FindNext $R0 $R1
  StrCmp $R1 "" VID_ValidClosed
  Goto VID_Scan
VID_ValidClosed:
  FindClose $R0
VID_Valid:
  Pop $R1
  Pop $R0
  Return
VID_Dirty:
  Pop $R1
  Pop $R0
  IfSilent VID_SilentFail
  MessageBox MB_OK|MB_ICONSTOP \
    "安装目录必须是 MdNote 专用文件夹：$\r$\n$\r$\n\
    • 文件夹不存在或为空，或$\r$\n\
    • 其中已有 MdNote 安装（用于升级）。$\r$\n$\r$\n\
    请不要选择包含其他资料的文件夹；卸载时也只会删除应用自身的文件。"
  Abort
VID_SilentFail:
  SetErrorLevel 3
  Quit
FunctionEnd

Function .onInit
  SetRegView 64
  ReadRegStr $0 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" "InstallLocation"
  StrCmp $0 "" keep_default
  StrCpy $INSTDIR $0
keep_default:
  ; An explicit /D= destination (including paths with spaces) wins over the registry.
  ${GetParameters} $1
  ClearErrors
  ${GetOptions} $1 "/D=" $2
  IfErrors destination_ready
  StrCmp $2 "" destination_ready
  StrCpy $INSTDIR $2
destination_ready:
  Call EnsureMdNoteClosed
  ; Silent installs never show the directory page, so validate explicitly.
  Call ValidateInstallDir
FunctionEnd

Function un.onInit
  Call un.EnsureMdNoteClosed
FunctionEnd

Section "MdNote（必需）" SecCore
  SectionIn RO
  Call EnsureMdNoteClosed
  Call ValidateInstallDir
  SetRegView 64
  !insertmacro MDNOTE_INSTALL_FILES

  CreateDirectory "$SMPROGRAMS\MdNote"
  CreateShortcut "$SMPROGRAMS\MdNote\MdNote.lnk" "$INSTDIR\MdNote.exe" "" "$INSTDIR\MdNote.exe" 0
  CreateShortcut "$SMPROGRAMS\MdNote\卸载 MdNote.lnk" "$INSTDIR\Uninstall.exe" "" "$INSTDIR\MdNote.exe" 0
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" "DisplayName" "MdNote"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" "Publisher" "MdNote"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" "DisplayIcon" "$INSTDIR\MdNote.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" "UninstallString" '$"$INSTDIR\Uninstall.exe$"'
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" "NoRepair" 1
SectionEnd

Section /o "桌面快捷方式" SecDesktop
  CreateShortcut "$DESKTOP\MdNote.lnk" "$INSTDIR\MdNote.exe" "" "$INSTDIR\MdNote.exe" 0
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecCore} "MdNote 应用程序及运行所需文件（必需）。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "在桌面创建 MdNote 快捷方式。"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  Call un.EnsureMdNoteClosed
  SetRegView 64
  Delete "$SMPROGRAMS\MdNote\MdNote.lnk"
  Delete "$SMPROGRAMS\MdNote\卸载 MdNote.lnk"
  RMDir "$SMPROGRAMS\MdNote"
  Delete "$DESKTOP\MdNote.lnk"
  SetOutPath "$TEMP"
  !insertmacro MDNOTE_REMOVE_INSTALLED_FILES
  Delete "$INSTDIR\Uninstall.exe"
  ; RMDir without /r succeeds only when empty, preserving user documents/assets.
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote"
SectionEnd
