# Проверка собранного установщика на чистой машине (раннере): установка,
# установка поверх — одна запись в «Установленных приложениях» и без файлов
# прошлой версии, — тихое удаление, которое не трогает настройки.
# Ждёт в окружении VERSION и ASSET. AppId — как в packaging/windows/LogDog.iss.
$ErrorActionPreference = "Stop"
$setup = "$PWD\$env:ASSET-setup.exe"
$app = Join-Path $env:LOCALAPPDATA "Programs\LogDog"
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{6C3F8A1E-4B7D-4E2A-9F1C-0D5E7B2A9C41}_is1"
$flags = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")

Start-Process -Wait -FilePath $setup -ArgumentList $flags
if (-not (Test-Path "$app\LogDog.exe")) { throw "после установки нет $app\LogDog.exe" }
if (-not (Test-Path "$app\unins000.exe")) { throw "нет деинсталлятора — обновление не поймёт, что копия установлена" }
$entry = Get-ItemProperty $key
if ($entry.DisplayVersion -ne $env:VERSION) { throw "версия в списке приложений: $($entry.DisplayVersion)" }
if ($entry.Publisher -ne "TimBeket") { throw "издатель: $($entry.Publisher)" }
if ($entry.DisplayName -ne "LogDog") { throw "название в списке приложений: $($entry.DisplayName)" }
if (-not (Test-Path (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\LogDog.lnk"))) {
  throw "нет ярлыка в «Пуске» (галочка по умолчанию включена)"
}

New-Item -ItemType File -Force "$app\_internal\stale-from-old-version.dll" | Out-Null
Start-Process -Wait -FilePath $setup -ArgumentList $flags   # обновление поверх
if (Test-Path "$app\_internal\stale-from-old-version.dll") { throw "файлы старой версии не убраны" }
$entries = Get-ChildItem "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall" |
  Where-Object { (Get-ItemProperty $_.PSPath).DisplayName -eq "LogDog" }
if (@($entries).Count -ne 1) { throw "записей LogDog в списке приложений: $(@($entries).Count)" }

$data = Join-Path $env:LOCALAPPDATA "LogDog"
New-Item -ItemType Directory -Force $data | Out-Null
Set-Content "$data\settings.ini" "[General]"
Start-Process -Wait -FilePath "$app\unins000.exe" -ArgumentList $flags
# деинсталлятор перезапускает себя из temp и сразу выходит — ждём по факту
for ($i = 0; $i -lt 60 -and (Test-Path $key); $i++) { Start-Sleep -Seconds 1 }
if (Test-Path "$app\LogDog.exe") { throw "после удаления программа осталась" }
if (Test-Path $key) { throw "после удаления осталась запись в списке приложений" }
if (-not (Test-Path "$data\settings.ini")) { throw "тихое удаление стёрло настройки" }
Write-Host "Установщик: установка, обновление поверх и удаление — в порядке"
