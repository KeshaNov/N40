# Сборка N40 (папка dist\N40, переносной zip и установщик). Запуск из корня репозитория:
#   powershell -File packaging\build.ps1
# Нужен Python 3.8 x64 (последняя версия с поддержкой Windows 7) — передайте путь в $env:N40_PYTHON
# или сделайте его первым python в PATH. На CI $env:N40_BUILD_BOOTLOADER=1 собирает загрузчик
# PyInstaller из исходников (нужен Visual C++): уникальный загрузчик реже попадает в базы антивирусов.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$py = if ($env:N40_PYTHON) { $env:N40_PYTHON } else { "python" }

$ver = (& $py -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
if ($ver -ne "3.8") { Write-Warning "Сборка на Python ${ver}: N40.exe не запустится на Windows 7 (нужен 3.8)" }

& $py -m pip install -r packaging\requirements-release.txt
if ($LASTEXITCODE -ne 0) { throw "Не удалось установить зависимости" }
if ($env:N40_BUILD_BOOTLOADER) {
    $env:PYINSTALLER_COMPILE_BOOTLOADER = "1"
    & $py -m pip install --force-reinstall --no-binary pyinstaller --no-cache-dir "pyinstaller==5.13.2"
} else {
    & $py -m pip install "pyinstaller==5.13.2"
}
& $py packaging\make_assets.py
if ($LASTEXITCODE -ne 0) { throw "make_assets.py завершился с ошибкой" }
$version = (& $py -c "import n40; print(n40.__version__)").Trim()

Remove-Item -Recurse -Force dist\N40, dist\N40-portable-*.zip -ErrorAction SilentlyContinue
Push-Location packaging
& $py -m PyInstaller n40.spec --noconfirm --distpath ..\dist --workpath ..\build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с ошибкой" }
Pop-Location

Compress-Archive -Path dist\N40 -DestinationPath "dist\N40-portable-$version.zip" -Force

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc "/DAppVersion=$version" packaging\n40.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup завершился с ошибкой" }
    Write-Host "Готово: dist\N40-Setup-$version.exe и dist\N40-portable-$version.zip"
} else {
    Write-Warning "Inno Setup 6 не найден — собраны только dist\N40 и переносной zip"
}
