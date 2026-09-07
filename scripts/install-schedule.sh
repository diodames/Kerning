#!/bin/bash
# Install a LaunchAgent that rebuilds Kerning at 00:20 local if Daily,
# Weekly, or Monthly have gone stale.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"
LABEL="com.kerning.fetch"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG="$ROOT/.kerning-fetch.log"

if [ -z "$PY" ]; then
  echo "python3 not found" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"

if [ -f "$PLIST" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PY}</string>
    <string>${ROOT}/kerning_fetch.py</string>
    <string>--limit</string>
    <string>12</string>
    <string>--if-stale</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>0</integer>
    <key>Minute</key>
    <integer>20</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${LOG}</string>
  <key>StandardErrorPath</key>
  <string>${LOG}</string>
</dict>
</plist>
EOF

launchctl load "$PLIST"
echo "Installed ${PLIST}"
echo "Rebuilds at 00:20 if yesterday, this week, or this month are stale."
echo "Log: ${LOG}"
