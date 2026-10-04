#!/bin/zsh
set -e
cd "$(dirname "$0")"

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

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python app.py
