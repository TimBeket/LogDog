# Сборка установщика LogDog (packaging/windows/LogDog.iss) из dist\LogDog.
# Ждёт в окружении VERSION, NUMVER (a.b.c.d) и ASSET (LogDog-<версия>-windows);
# результат — $ASSET-setup.exe в текущей папке.
$ErrorActionPreference = "Stop"
$iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
& $iscc "/DAppVersion=$env:VERSION" "/DAppNumVersion=$env:NUMVER" `
  "/DSourceDir=$PWD\dist\LogDog" "/DOutputBase=$env:ASSET-setup" "/O$PWD" packaging\windows\LogDog.iss
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
