#!/bin/zsh
set -e

cd "$(dirname "$0")"

APP="dist/NotRoyalTs.app"

if [ ! -d "$APP" ]; then
  echo "NotRoyalTs.app has not been built yet."
  echo "Run ./build-macos.sh first."
  exit 1
fi

echo "Installing NotRoyalTs.app into /Applications..."
rm -rf "/Applications/NotRoyalTs.app"
cp -R "$APP" "/Applications/NotRoyalTs.app"

echo "Installed:"
echo "  /Applications/NotRoyalTs.app"
echo
echo "You can now launch NotRoyalTs from Finder, Spotlight, or the Dock."
