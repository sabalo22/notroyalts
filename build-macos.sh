#!/bin/zsh
set -e

cd "$(dirname "$0")"

APP_NAME="NotRoyalTs"
BUNDLE_ID="com.notroyalts.app"

if [ -x /usr/local/bin/python3.12 ]; then
  PY=/usr/local/bin/python3.12
elif [ -x /opt/homebrew/bin/python3.12 ]; then
  PY=/opt/homebrew/bin/python3.12
else
  PY=$(command -v python3)
fi

if [ -z "$PY" ]; then
  echo "Python 3 was not found."
  exit 1
fi

echo "Using: $($PY --version)"

rm -rf .venv-build build dist "${APP_NAME}.spec"

"$PY" -m venv .venv-build
source .venv-build/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-build.txt

echo
echo "Building ${APP_NAME}.app..."
python -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --osx-bundle-identifier "$BUNDLE_ID" \
  --hidden-import pyte \
  app.py

APP_PATH="$(pwd)/dist/${APP_NAME}.app"

if [ ! -d "$APP_PATH" ]; then
  echo "Build failed: ${APP_NAME}.app was not created."
  exit 1
fi

if command -v codesign >/dev/null 2>&1; then
  echo "Applying local ad-hoc signature..."
  codesign --force --deep --sign - "$APP_PATH" || true
fi

echo
echo "Build complete:"
echo "  $APP_PATH"
echo
echo "To install it:"
echo "  cp -R \"$APP_PATH\" /Applications/"
echo
echo "Or double-click dist/${APP_NAME}.app to test it first."
