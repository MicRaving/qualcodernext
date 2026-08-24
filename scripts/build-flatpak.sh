#!/usr/bin/env bash
# Build QCnext on Linux — self-contained, no prior setup needed.
# Produces a .deb (the stock Tauri CLI cannot bundle .flatpak directly).
# Usage: ./build-flatpak.sh [path/to/repo]
set -euo pipefail
REPO="${1:-$(pwd)}"
cd "$REPO"

echo "== 1/6 system packages =="
sudo apt-get update -qq
sudo apt-get install -y \
  build-essential curl wget file pkg-config libssl-dev \
  libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev \
  librsvg2-dev libxdo-dev patchelf \
  flatpak flatpak-builder nodejs npm python3 python3-venv python3-pip \
  libgomp1

flatpak remote-add --if-not-exists --user flathub https://flathub.org/repo/flathub.flatpakrepo || true

echo "== 2/6 Rust toolchain =="
if ! command -v cargo &>/dev/null; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
  source "$HOME/.cargo/env"
fi

echo "== 3/6 frontend =="
cd frontend
npm ci
npm run build
cd ..

echo "== 4/6 backend onedir =="
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]" pyinstaller
python -m PyInstaller --noconfirm qualcoder_backend.spec
deactivate
cd ..

echo "== 5/6 copy backend into Tauri resources =="
mkdir -p frontend/src-tauri/resources/backend
cp -r backend/dist/qualcoder-backend/* frontend/src-tauri/resources/backend/

echo "== 6/6 tauri build (deb bundle — see note) =="
cd frontend/src-tauri
# NOTE: the stock Tauri v2 CLI cannot emit .flatpak bundles (--bundles on
# Linux only accepts deb, rpm, appimage). Build the .deb here; wrapping it
# into a .flatpak requires a flatpak-builder manifest (see tauri docs:
# https://v2.tauri.app/distribute/flatpak/).
npx --yes @tauri-apps/cli@2 build --bundles deb

BUNDLE=$(find target/release/bundle/deb -name "*.deb" 2>/dev/null | head -1)
echo ""
echo "== DONE =="
echo "Deb package: $BUNDLE"
echo "Install:     sudo apt install $BUNDLE"
echo "A .flatpak wrapper must be built from a flatpak-builder manifest."
