#!/bin/sh
# Runs as root only long enough to own /data (a bind mount arrives owned by the host directory's owner),
# then becomes PUID:PGID with exec, so the miner is PID 1 and `docker stop` reaches it directly.
set -e
PUID="${PUID:-99}"
PGID="${PGID:-100}"
mkdir -p "$DROPWATCH_DATA"
chown -R "$PUID:$PGID" "$DROPWATCH_DATA"
exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
