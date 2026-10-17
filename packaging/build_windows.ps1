# Gera dist\StickerStudio.exe (arquivo único) e dist\StickerStudio-windows-x64.zip (pasta portátil).
# Requisitos: Python 3.10+ com requirements.txt + pyinstaller.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$ff = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip"
New-Item -ItemType Directory -Force build-cache, build, dist | Out-Null
if (-not (Test-Path build-cache\ffmpeg-win.zip)) { Invoke-WebRequest $ff -OutFile build-cache\ffmpeg-win.zip }
if (Test-Path build-cache\ffmpeg-win) { Remove-Item -Recurse -Force build-cache\ffmpeg-win }
Expand-Archive build-cache\ffmpeg-win.zip build-cache\ffmpeg-win
$src = Get-ChildItem build-cache\ffmpeg-win -Directory | Select-Object -First 1
if (Test-Path ffmpeg-bin) { Remove-Item -Recurse -Force ffmpeg-bin }
New-Item -ItemType Directory ffmpeg-bin | Out-Null
Copy-Item "$($src.FullName)\bin\*" ffmpeg-bin\ -Exclude ffplay.exe
Copy-Item "$($src.FullName)\LICENSE.txt" ffmpeg-bin\FFMPEG-LICENSE.txt

python packaging\make_icons.py
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyi packaging\sticker-studio.spec
Compress-Archive -Force dist\StickerStudio\* dist\StickerStudio-windows-x64.zip
$env:ONEFILE = "1"
python -m PyInstaller --noconfirm --distpath dist --workpath build\pyi1 packaging\sticker-studio.spec
Remove-Item -Recurse -Force ffmpeg-bin
Write-Host "pronto: dist\StickerStudio.exe e dist\StickerStudio-windows-x64.zip"
