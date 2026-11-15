#!/usr/bin/env bash
# Copy a renewed TLS certificate into Mosquitto's folder and make the broker reload it, safely.
#
# Typical use: Nginx Proxy Manager (or certbot) renews a Let's Encrypt certificate; run this from
# cron as root a few times a day. It does nothing when the certificate has not changed.
#
#   deploy-mosquitto-cert.sh --src /path/to/letsencrypt/live/npm-1 \
#                            --dest /home/me/docker/mosquitto/certs \
#                            --server-name mqtt.example.com
#
# What it checks, in order:
#   1. the certificate and the key belong together and the certificate is not expired
#   2. the files are given to the broker's user (Mosquitto drops privileges after start, so a
#      reload cannot read root-owned files and the TLS listener would lose its certificate)
#   3. after the reload, the broker really presents the new certificate; if it does not, the
#      previous files are put back and the broker reloads them again
set -euo pipefail

SRC="" DEST="" CONTAINER="mosquitto" OWNER="1883:1883"
SERVER_NAME="" VERIFY_ADDR="127.0.0.1" VERIFY_PORT="8883" INSTALL_ONLY=0

usage() {
  cat <<EOF
Usage: $(basename "$0") --src DIR --dest DIR [options]

  --src DIR            folder with fullchain.pem and privkey.pem (e.g. NPM's letsencrypt/live/npm-N)
  --dest DIR           Mosquitto's certificate folder (mounted at /mosquitto/certs)
  --container NAME     broker container to signal (default: mosquitto)
  --owner UID:GID      owner of the deployed files (default: 1883:1883, the broker's user)
  --server-name NAME   TLS server name used for the final check (your certificate's hostname)
  --verify-addr ADDR   where the broker's TLS port is reachable (default: 127.0.0.1)
  --verify-port PORT   the TLS port (default: 8883)
  --install-only       only put the files in place, without reloading or checking the broker
                       (for the very first time, before the TLS listener exists)
EOF
}

log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --src) SRC="$2"; shift 2 ;;
    --dest) DEST="$2"; shift 2 ;;
    --container) CONTAINER="$2"; shift 2 ;;
    --owner) OWNER="$2"; shift 2 ;;
    --server-name) SERVER_NAME="$2"; shift 2 ;;
    --verify-addr) VERIFY_ADDR="$2"; shift 2 ;;
    --verify-port) VERIFY_PORT="$2"; shift 2 ;;
    --install-only) INSTALL_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[ -n "$SRC" ] && [ -n "$DEST" ] || { usage >&2; exit 2; }

CERT_SRC="$SRC/fullchain.pem"
KEY_SRC="$SRC/privkey.pem"
[ -r "$CERT_SRC" ] && [ -r "$KEY_SRC" ] || die "cannot read fullchain.pem and privkey.pem in $SRC"

# --- 1. sanity checks on the new files
cert_pub=$(openssl x509 -in "$CERT_SRC" -noout -pubkey | sha256sum | cut -d' ' -f1)
key_pub=$(openssl pkey -in "$KEY_SRC" -pubout | sha256sum | cut -d' ' -f1)
[ "$cert_pub" = "$key_pub" ] || die "the certificate and the private key do not match; nothing changed"
openssl x509 -in "$CERT_SRC" -noout -checkend 0 >/dev/null || die "the certificate is already expired; nothing changed"

if [ -f "$DEST/fullchain.pem" ] && [ -f "$DEST/privkey.pem" ] \
   && cmp -s "$CERT_SRC" "$DEST/fullchain.pem" && cmp -s "$KEY_SRC" "$DEST/privkey.pem"; then
  log "already up to date"
  exit 0
fi

fingerprint() { openssl x509 -noout -fingerprint -sha256; }
presented() {
  # the fingerprint of the certificate the broker is serving right now (empty if none)
  if [ -n "$SERVER_NAME" ]; then
    echo | openssl s_client -connect "$VERIFY_ADDR:$VERIFY_PORT" -servername "$SERVER_NAME" 2>/dev/null | fingerprint 2>/dev/null || true
  else
    echo | openssl s_client -connect "$VERIFY_ADDR:$VERIFY_PORT" 2>/dev/null | fingerprint 2>/dev/null || true
  fi
}
reload_broker() { docker kill -s HUP "$CONTAINER" >/dev/null || die "cannot signal container '$CONTAINER'"; sleep 2; }

# --- 2. put the files in place, owned by the broker's user
mkdir -p "$DEST"
HAD_PREV=0
if [ -f "$DEST/fullchain.pem" ] && [ -f "$DEST/privkey.pem" ]; then
  cp -p "$DEST/fullchain.pem" "$DEST/fullchain.pem.prev"
  cp -p "$DEST/privkey.pem" "$DEST/privkey.pem.prev"
  HAD_PREV=1
fi
install -o "${OWNER%%:*}" -g "${OWNER##*:}" -m 0644 "$CERT_SRC" "$DEST/fullchain.pem.new"
install -o "${OWNER%%:*}" -g "${OWNER##*:}" -m 0600 "$KEY_SRC" "$DEST/privkey.pem.new"
mv -f "$DEST/privkey.pem.new" "$DEST/privkey.pem"
mv -f "$DEST/fullchain.pem.new" "$DEST/fullchain.pem"

if [ "$INSTALL_ONLY" = 1 ]; then
  log "files installed in $DEST (broker not signalled)"
  exit 0
fi

# --- 3. reload and check
want=$(fingerprint < "$DEST/fullchain.pem")
reload_broker
got=$(presented)
if [ "$got" = "$want" ]; then
  log "certificate deployed and loaded by the broker ($want)"
  exit 0
fi

log "ERROR: the broker does not present the new certificate (got: '${got:-nothing}')"
if [ "$HAD_PREV" = 1 ]; then
  log "putting the previous certificate back"
  mv -f "$DEST/privkey.pem.prev" "$DEST/privkey.pem"
  mv -f "$DEST/fullchain.pem.prev" "$DEST/fullchain.pem"
  reload_broker
  log "after rollback the broker presents: '$(presented)'"
else
  log "there was no previous certificate to restore; check the files in $DEST and the broker log"
fi
exit 1
