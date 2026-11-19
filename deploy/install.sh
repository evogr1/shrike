#!/usr/bin/env bash
# Shrike installer (Phase 0). Idempotent: run it, fill in the env file and config, run it again.
# Usage: sudo /opt/shrike/deploy/install.sh
set -euo pipefail

REPO=/opt/shrike
ETC=/etc/shrike
DATA=/var/lib/shrike
UNITS=/etc/systemd/system

[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)"; exit 1; }
[ -f "$REPO/pyproject.toml" ] || { echo "clone the repo to $REPO first"; exit 1; }
command -v python3 >/dev/null || { echo "python3 (3.11+) is required"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || { echo "python 3.11+ required"; exit 1; }

# 1. user and directories
id shrike >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin shrike
install -d -o root -g shrike -m 750 "$ETC"
install -d -o shrike -g shrike -m 700 "$DATA"

# 2. virtualenv and package
[ -x "$REPO/venv/bin/python" ] || python3 -m venv "$REPO/venv"
"$REPO/venv/bin/pip" install -q --upgrade pip
"$REPO/venv/bin/pip" install -q -r "$REPO/requirements.txt"
"$REPO/venv/bin/pip" install -q --no-deps --force-reinstall "$REPO"

# 3. templates (never overwritten)
if [ ! -f "$ETC/config.toml" ]; then
  install -o root -g shrike -m 640 "$REPO/config.example.toml" "$ETC/config.toml"
  echo "created $ETC/config.toml"
fi
if [ ! -f "$ETC/env" ]; then
  install -o root -g root -m 600 /dev/null "$ETC/env"
  echo "created empty $ETC/env"
fi

# 4. units
for u in shrike-nightly.service shrike-backfill.service shrike-setup.service shrike-alert@.service; do
  install -o root -g root -m 644 "$REPO/deploy/systemd/$u" "$UNITS/$u"
done

# 5. stop here until secrets are filled in
if ! grep -q '^SHRIKE_TRELLO_TOKEN=.\+' "$ETC/env"; then
  cat <<EOF

Next steps:
  1. Put the service-account key at $ETC/sa.json (owner shrike, mode 600):
       install -o shrike -g shrike -m 600 key.json $ETC/sa.json
  2. Fill in $ETC/env (see $REPO/.env.example) and $ETC/config.toml.
  3. Run this script again.
See $REPO/docs/SETUP.md for each step.
EOF
  exit 0
fi

# 6. timers from config
SHRIKE_CONFIG="$ETC/config.toml" "$REPO/venv/bin/shrike" render-units --out "$UNITS"
systemctl daemon-reload

# 7. setup check, as the shrike user with the env file and state directory
if ! systemctl start --wait shrike-setup.service; then
  rc=$(systemctl show -p ExecMainStatus --value shrike-setup.service)
  if [ "$rc" = "3" ]; then
    echo "A backfill or nightly run is still in progress. Wait for it (journalctl -fu shrike-backfill), then run this script again."
    exit 1
  fi
  echo
  echo "Setup check found problems:"
  journalctl -u shrike-setup.service -n 40 --no-pager -o cat || true
  echo "Fix them and run this script again."
  exit 1
fi
journalctl -u shrike-setup.service -n 40 --no-pager -o cat || true

# 8. first backfill (only once)
if [ ! -f "$DATA/.backfill-started" ]; then
  systemctl start --no-block shrike-backfill.service
  touch "$DATA/.backfill-started" && chown shrike:shrike "$DATA/.backfill-started"
  echo "backfill started: journalctl -fu shrike-backfill.service"
fi

# 9. nightly timer (nights that start during the backfill exit 3 and still ping)
systemctl enable --now shrike-nightly.timer
echo "done. Nightly timer enabled: systemctl list-timers shrike-nightly.timer"
