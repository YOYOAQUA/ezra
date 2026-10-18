#!/usr/bin/env bash
# Ezra installer (Mac / Linux): creates ~/Ezra, the `ezra` shortcut, config.json and an empty key file.
# Nothing is downloaded and nothing is sent anywhere.
set -e
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${EZRA_HOME:-$HOME/Ezra}"

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null; then
  echo "✗ Python 3 is missing. On a Mac run: xcode-select --install  (press Install, wait, then run this again)"
  exit 1
fi

mkdir -p "$DIR"
cat > "$DIR/ezra" <<WRAP
#!/usr/bin/env bash
export EZRA_HOME="$DIR"
exec python3 "$SKILL/scripts/ezra.py" "\$@"
WRAP
chmod +x "$DIR/ezra"

[ -f "$DIR/config.json" ] || cp "$SKILL/templates/config.example.json" "$DIR/config.json"
if [ ! -f "$DIR/.env" ]; then
  printf '# Paste your Zernio API key right after the = sign, save, close.\nZERNIO_API_KEY=\n' > "$DIR/.env"
fi
chmod 600 "$DIR/.env"

echo "✓ Ezra $(python3 "$SKILL/scripts/ezra.py" --version) is ready in $DIR"
echo "  next: $DIR/ezra key   (opens the key file)   then   $DIR/ezra check"
