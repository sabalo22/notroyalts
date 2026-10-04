#!/bin/zsh
set -e

cd "$(dirname "$0")"

APP_NAME="NotRoyalTs"
BUNDLE_ID="com.notroyalts.app"

ARCH="$(uname -m)"
ROSETTA="$(sysctl -in sysctl.proc_translated 2>/dev/null || echo 0)"

if [ "$ROSETTA" = "1" ]; then
  echo "Refusing to build an Intel/Rosetta app on Apple Silicon."
  echo "Open a native arm64 shell and run ./build-macos.sh again."
  echo
  echo "Example:"
  echo "  arch -arm64 /bin/zsh --login"
  echo "  ./build-macos.sh"
  exit 1
fi

valid_python() {
  local candidate="$1"

  [ -x "$candidate" ] || return 1

  "$candidate" -c '
import platform, sys
expected = sys.argv[1]
ok_version = sys.version_info >= (3, 10)
ok_arch = platform.machine() == expected
raise SystemExit(0 if ok_version and ok_arch else 1)
' "$ARCH" >/dev/null 2>&1
}

PY=""

if [ "$ARCH" = "arm64" ]; then
  for candidate in     /opt/homebrew/bin/python3.12     /opt/homebrew/bin/python3     "$(command -v python3 2>/dev/null || true)"
  do
    if valid_python "$candidate"; then
      PY="$candidate"
      break
    fi
  done
else
  for candidate in     /usr/local/bin/python3.12     /usr/local/bin/python3     "$(command -v python3 2>/dev/null || true)"
  do
    if valid_python "$candidate"; then
      PY="$candidate"
      break
    fi
  done
fi

if [ -z "$PY" ]; then
  echo "A native Python 3.10+ installation was not found for architecture: $ARCH"
  if [ "$ARCH" = "arm64" ]; then
    echo "Recommended:"
    echo "  /opt/homebrew/bin/brew install python@3.12"
  fi
  exit 1
fi

echo "Using: $PY"
"$PY" -c 'import platform,sys; print(f"Python {sys.version.split()[0]} ({platform.machine()})")'

rm -rf .venv-build build dist "${APP_NAME}.spec"

"$PY" -m venv .venv-build
source .venv-build/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-build.txt

echo
echo "Building ${APP_NAME}.app for ${ARCH}..."
python -m PyInstaller   --noconfirm   --clean   --windowed   --name "$APP_NAME"   --osx-bundle-identifier "$BUNDLE_ID"   --hidden-import pyte   app.py

APP_PATH="$(pwd)/dist/${APP_NAME}.app"
APP_EXE="$APP_PATH/Contents/MacOS/$APP_NAME"

if [ ! -d "$APP_PATH" ]; then
  echo "Build failed: ${APP_NAME}.app was not created."
  exit 1
fi

if [ -f "$APP_EXE" ]; then
  echo "Built executable:"
  file "$APP_EXE"
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
