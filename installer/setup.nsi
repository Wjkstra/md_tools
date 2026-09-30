; =============================================================
; MdNote NSIS 安装程序脚本
; 构建（在仓库根目录）： makensis installer/setup.nsi
; 特性：自定义安装路径、开始菜单 / 桌面快捷方式、卸载程序
; =============================================================

Unicode True

!include "MUI2.nsh"

Name "MdNote"
OutFile "..\MdNote-Setup.exe"

; 默认安装到 Program Files；安装时可在目录页自定义
InstallDir "$PROGRAMFILES64\MdNote"
RequestExecutionLevel admin

; 安装后保留的压缩数据
ShowInstDetails hide
ShowUninstDetails hide

; ---------------- 页面 ----------------

!define MUI_ABORTWARNING

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; ---------------- 语言 ----------------

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

; ---------------- 安装主段 ----------------

Section "MdNote（必需）" SecCore
  SectionIn RO

  SetRegView 64
  SetOutPath "$INSTDIR"
  ; 复制 PyInstaller 打包目录的全部内容
  File /r "..\dist\MdNote\*"

  ; 开始菜单
  CreateDirectory "$SMPROGRAMS\MdNote"
  CreateShortcut "$SMPROGRAMS\MdNote\MdNote.lnk" \
    "$INSTDIR\MdNote.exe" "" "$INSTDIR\MdNote.exe" 0
  CreateShortcut "$SMPROGRAMS\MdNote\卸载 MdNote.lnk" \
    "$INSTDIR\Uninstall.exe" "" "$INSTDIR\Uninstall.exe" 0

  ; 写入卸载程序
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; 注册“添加 / 删除程序”信息
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" \
    "DisplayName" "MdNote"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" \
    "DisplayVersion" "0.1.0"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" \
    "Publisher" "MdNote"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" \
    "DisplayIcon" "$INSTDIR\MdNote.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" \
    "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" \
    "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" \
    "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote" \
    "NoRepair" 1
SectionEnd

; ---------------- 可选：桌面快捷方式 ----------------

Section /o "桌面快捷方式" SecDesktop
  CreateShortcut "$DESKTOP\MdNote.lnk" \
    "$INSTDIR\MdNote.exe" "" "$INSTDIR\MdNote.exe" 0
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecCore} "MdNote 应用程序及运行所需文件（必需）。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "在桌面创建 MdNote 快捷方式。"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ---------------- 卸载 ----------------

Section "Uninstall"
  SetRegView 64
  ; 删除快捷方式
  Delete "$SMPROGRAMS\MdNote\MdNote.lnk"
  Delete "$SMPROGRAMS\MdNote\卸载 MdNote.lnk"
  RMDir "$SMPROGRAMS\MdNote"
  Delete "$DESKTOP\MdNote.lnk"

  ; 删除安装目录全部内容
  RMDir /r "$INSTDIR"
  RMDir "$INSTDIR"

  ; 清理注册表
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MdNote"
SectionEnd
