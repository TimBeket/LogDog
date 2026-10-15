; Установщик LogDog для Windows (Inno Setup 6, есть на windows-раннерах GitHub).
;
; Собирается в release.yml из той же папки PyInstaller, что и portable-zip:
;   ISCC /DAppVersion=1.2 /DAppNumVersion=1.2.0.0 /DSourceDir=dist\LogDog
;        /DOutputBase=LogDog-1.2-windows-setup packaging\windows\LogDog.iss
;
; Важное:
; - Установка для текущего пользователя (%LOCALAPPDATA%\Programs\LogDog), без
;   прав администратора и запроса UAC: в компании их часто нет, а обновление
;   из программы не смогло бы писать в Program Files.
; - AppId постоянный: новая версия ставится поверх старой и обновляет ту же
;   запись в «Установленных приложениях» — второй строки не появляется.
;   НЕ МЕНЯТЬ — иначе у пользователей окажутся две установки.
; - Обновление из программы (core/update_install.py) запускает этот же
;   установщик с /SILENT: окно с прогрессом, без вопросов; /RELAUNCH=1 —
;   запустить LogDog после установки.
; - Настройки и история фильтров лежат отдельно (%LOCALAPPDATA%\LogDog, см.
;   utils/helpers.get_app_data_dir): при удалении спрашиваем, удалять ли их.

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#ifndef AppNumVersion
  #define AppNumVersion "0.0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\LogDog"
#endif
#ifndef OutputBase
  #define OutputBase "LogDog-setup"
#endif

[Setup]
AppId={{6C3F8A1E-4B7D-4E2A-9F1C-0D5E7B2A9C41}
AppName=LogDog
AppVersion={#AppVersion}
AppVerName=LogDog {#AppVersion}
AppPublisher=TimBeket
AppPublisherURL=https://github.com/TimBeket/LogDog
AppSupportURL=https://github.com/TimBeket/LogDog/issues
AppUpdatesURL=https://github.com/TimBeket/LogDog/releases
VersionInfoVersion={#AppNumVersion}
VersionInfoProductName=LogDog
DefaultDirName={localappdata}\Programs\LogDog
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=LogDog
UninstallDisplayIcon={app}\LogDog.exe
SetupIconFile=..\..\assets\icon.ico
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputDir=.
OutputBaseFilename={#OutputBase}
; LogDog открыт — закрыть его перед заменой файлов (при обновлении из
; программы он закрывается сам, это на случай ручного запуска установщика)
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startmenu"; Description: "Создать ярлык в меню «Пуск»"; GroupDescription: "Ярлыки:"
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: unchecked

[InstallDelete]
; Библиотеки прошлой версии — долой целиком: иначе при обновлении поверх
; оставались бы лишние файлы старых версий Qt/Python.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\LogDog"; Filename: "{app}\LogDog.exe"; Tasks: startmenu
Name: "{autodesktop}\LogDog"; Filename: "{app}\LogDog.exe"; Tasks: desktopicon

[Run]
; Обычная установка — галочка «Запустить LogDog» на последней странице.
Filename: "{app}\LogDog.exe"; Description: "Запустить LogDog"; Flags: nowait postinstall skipifsilent
; Обновление из программы (/SILENT /RELAUNCH=1) — запустить новую версию.
Filename: "{app}\LogDog.exe"; Flags: nowait; Check: RelaunchRequested

[Code]
function RelaunchRequested: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\LogDog');
    // Тихое удаление — данные не трогаем; обычное — спрашиваем, по умолчанию «Нет».
    if (not UninstallSilent) and DirExists(DataDir) then
      if MsgBox('Удалить также настройки LogDog и историю фильтров?' + #13#10#13#10 +
                'Они нужны, если вы собираетесь установить LogDog снова.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
