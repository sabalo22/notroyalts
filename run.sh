#!/bin/zsh
set -e
cd "$(dirname "$0")"

ARCH="$(uname -m)"
ROSETTA="$(sysctl -in sysctl.proc_translated 2>/dev/null || echo 0)"

if [ "$ROSETTA" = "1" ]; then
  echo "NotRoyalTs is running from an Intel/Rosetta shell on Apple Silicon."
  echo "Please open a native arm64 shell and run this script again."
  echo
  echo "Example:"
  echo "  arch -arm64 /bin/zsh --login"
  echo "  ./run.sh"
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

if [ -d .venv ]; then
  if ! .venv/bin/python -c '
import platform, sys
expected = sys.argv[1]
raise SystemExit(0 if sys.version_info >= (3, 10) and platform.machine() == expected else 1)
' "$ARCH" >/dev/null 2>&1; then
    echo "Removing incompatible .venv..."
    rm -rf .venv
  fi
fi

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python app.py
