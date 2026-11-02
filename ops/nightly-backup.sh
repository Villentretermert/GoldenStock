#!/bin/sh
set -eu
config="${XDG_CONFIG_HOME:-$HOME/.config}/goldenstock/backup.env"
[ -f "$config" ] && [ ! -L "$config" ] && [ "$(stat -c %a "$config")" = 600 ] && [ "$(stat -c %u "$config")" = "$(id -u)" ] || {
  echo "Private, operator-owned backup.env (0600) required" >&2
  exit 1
}
set -a
. "$config"
set +a
project=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
exec flock -n "$config.lock" python3 "$project/scripts/backup_to_media.py" backup
