#!/usr/bin/env bash
# Gera dist/StickerStudio-x86_64.AppImage
# Requisitos: python 3.10+ com as dependências de requirements.txt + pyinstaller, curl, tar.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
PY=${PYTHON:-python3}
FF_URL=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl-shared.tar.xz
TOOL_URL=https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage

mkdir -p build-cache build dist
[ -f build-cache/ffmpeg-linux-shared.tar.xz ] || curl -fL -o build-cache/ffmpeg-linux-shared.tar.xz "$FF_URL"
[ -d build-cache/ffmpeg-master-latest-linux64-gpl-shared ] || tar -C build-cache -xJf build-cache/ffmpeg-linux-shared.tar.xz
[ -x build-cache/appimagetool ] || { curl -fL -o build-cache/appimagetool "$TOOL_URL"; chmod +x build-cache/appimagetool; }

"$PY" packaging/make_icons.py
rm -rf ffmpeg-bin build/pyi dist/StickerStudio
"$PY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyi packaging/sticker-studio.spec

APPDIR=build/AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a dist/StickerStudio "$APPDIR/app"
FF=build-cache/ffmpeg-master-latest-linux64-gpl-shared
mkdir -p "$APPDIR/ffmpeg"
cp -a "$FF/bin" "$FF/lib" "$FF/LICENSE.txt" "$APPDIR/ffmpeg/"
rm -f "$APPDIR/ffmpeg/bin/ffplay"
cp build/icon.png "$APPDIR/sticker-studio.png"
cp build/icon.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/sticker-studio.png"
cat > "$APPDIR/sticker-studio.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Sticker Studio
Comment=Figurinhas animadas para WhatsApp e Telegram a partir de vídeos
Exec=StickerStudio %f
Icon=sticker-studio
Categories=Graphics;AudioVideo;
MimeType=video/mp4;video/webm;video/quicktime;video/x-matroska;image/webp;image/gif;
Terminal=false
DESK
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export STICKER_STUDIO_FFMPEG_DIR="$HERE/ffmpeg/bin"
exec "$HERE/app/StickerStudio" "$@"
RUN
chmod +x "$APPDIR/AppRun"
ARCH=x86_64 ./build-cache/appimagetool --appimage-extract-and-run -n "$APPDIR" dist/StickerStudio-x86_64.AppImage
echo "pronto: dist/StickerStudio-x86_64.AppImage"
