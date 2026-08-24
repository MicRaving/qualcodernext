#!/usr/bin/env bash
# Build QCnext flatpak on Linux — self-contained, no prior setup needed.
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
flatpak install --assumeyes --user flathub org.freedesktop.Sdk//24.08 org.freedesktop.Platform//24.08 2>/dev/null || true

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

echo "== 6/6 tauri build (flatpak bundle) =="
cd frontend/src-tauri
npx --yes @tauri-apps/cli@2 build --bundles flatpak

BUNDLE=$(find target/release/bundle/flatpak -name "*.flatpak" 2>/dev/null | head -1)
echo ""
echo "== DONE =="
echo "Flatpak bundle: $BUNDLE"
echo "Install:        flatpak install --user $BUNDLE"
echo "Run:            flatpak run org.qcnext.desktop"
