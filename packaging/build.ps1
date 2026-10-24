# Сборка N40.exe и установщика.  Запуск из корня репозитория:  powershell -File packaging\build.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

python -m pip install -r requirements.txt pyinstaller
python packaging\make_assets.py
$version = (python -c "import n40; print(n40.__version__)").Trim()

Push-Location packaging
python -m PyInstaller n40.spec --noconfirm --distpath ..\dist --workpath ..\build
Pop-Location

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc "/DAppVersion=$version" packaging\n40.iss
    Write-Host "Готово: dist\N40-Setup-$version.exe"
} else {
    Write-Warning "Inno Setup 6 не найден — собран только dist\N40.exe"
}
