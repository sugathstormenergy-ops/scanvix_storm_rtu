#!/usr/bin/env bash
# =============================================================================
# TEST-ONLY: runs the PRODUCTION nginx configs with a local nginx binary so the
# routing can be tested without Docker:
#
#   :19080 / :19443  reverse proxy   <- docker/nginx/templates/storm.conf.template
#   :18080           storm-frontend  <- frontend/nginx.conf serving frontend/dist
#   :18000           API             <- e2e/fixture_api.py (started separately)
#
# Only the listen ports, upstream host names, TLS file paths, log targets and (for an
# older local nginx) the `http2 on;` line are rewritten; every location block is used
# exactly as shipped.
# Usage:  e2e/proxy-harness.sh start|stop   (WORK dir defaults to /tmp/storm-e2e)
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
WORK="${WORK:-/tmp/storm-e2e}"
MIME="${MIME:-/etc/nginx/mime.types}"

stop() {
  for n in proxy frontend; do
    [ -f "$WORK/$n.pid" ] && kill "$(cat "$WORK/$n.pid")" 2>/dev/null || true
  done
}

start() {
  stop
  mkdir -p "$WORK/certs" "$WORK/tmp"
  # nginx worker processes may run as an unprivileged user: serve a readable copy of dist/
  rm -rf "$WORK/html" && cp -r "$REPO/frontend/dist" "$WORK/html" && chmod -R a+rX "$WORK/html"
  if [ ! -f "$WORK/certs/tls.crt" ]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=storm-e2e.local" \
      -keyout "$WORK/certs/tls.key" -out "$WORK/certs/tls.crt" >/dev/null 2>&1
  fi

  # ---- storm-frontend (frontend/nginx.conf, unchanged locations) ----
  sed -e 's#listen 8080 default_server;#listen 127.0.0.1:18080 default_server;#' \
      -e "s#root /usr/share/nginx/html;#root $WORK/html;#" \
      -e "s#error_log /dev/stderr warn;#error_log $WORK/frontend-error.log warn;#" \
      "$REPO/frontend/nginx.conf" > "$WORK/frontend.server.conf"
  cat > "$WORK/frontend.nginx.conf" <<EOF
pid $WORK/frontend.pid;
error_log $WORK/frontend-error.log warn;
events {}
http {
  include $MIME;
  default_type application/octet-stream;
  client_body_temp_path $WORK/tmp; proxy_temp_path $WORK/tmp; fastcgi_temp_path $WORK/tmp;
  uwsgi_temp_path $WORK/tmp; scgi_temp_path $WORK/tmp;
  include $WORK/frontend.server.conf;
}
EOF

  # ---- reverse proxy (template rendered like the nginx image entrypoint does) ----
  sed -e 's#\${STORM_TLS_SERVER_NAME}#storm-e2e.local#' \
      -e "s#/etc/nginx/certs/\${STORM_TLS_CERT_FILE}#$WORK/certs/tls.crt#" \
      -e "s#/etc/nginx/certs/\${STORM_TLS_KEY_FILE}#$WORK/certs/tls.key#" \
      -e 's#listen 8080 default_server;#listen 127.0.0.1:19080 default_server;#' \
      -e 's#listen 8443 ssl default_server;#listen 127.0.0.1:19443 ssl default_server;#' \
      -e 's|^    http2 on;|    # http2 on;  (needs nginx >= 1.25.1; the image has 1.28)|' \
      -e 's#http://storm-api:8000#http://127.0.0.1:18000#' \
      -e 's#http://storm-frontend:8080#http://127.0.0.1:18080#' \
      -e "s#access_log /dev/stdout storm_main;#access_log $WORK/proxy-access.log storm_main;#" \
      -e "s#error_log  /dev/stderr warn;#error_log $WORK/proxy-error.log warn;#" \
      "$REPO/docker/nginx/templates/storm.conf.template" > "$WORK/proxy.server.conf"
  if grep -v '^[[:space:]]*#' "$WORK/proxy.server.conf" | grep -q '\${STORM_'; then echo "unrendered template variable" >&2; exit 1; fi
  cat > "$WORK/proxy.nginx.conf" <<EOF
pid $WORK/proxy.pid;
error_log $WORK/proxy-error.log warn;
events {}
http {
  include $MIME;
  default_type application/octet-stream;
  client_body_temp_path $WORK/tmp; proxy_temp_path $WORK/tmp; fastcgi_temp_path $WORK/tmp;
  uwsgi_temp_path $WORK/tmp; scgi_temp_path $WORK/tmp;
  include $WORK/proxy.server.conf;
}
EOF

  nginx -t -c "$WORK/frontend.nginx.conf" -e "$WORK/frontend-error.log"
  nginx -t -c "$WORK/proxy.nginx.conf" -e "$WORK/proxy-error.log"
  nginx -c "$WORK/frontend.nginx.conf" -e "$WORK/frontend-error.log"
  nginx -c "$WORK/proxy.nginx.conf" -e "$WORK/proxy-error.log"
  echo "proxy: http://127.0.0.1:19080  https://127.0.0.1:19443   frontend: http://127.0.0.1:18080"
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  *) echo "usage: $0 start|stop" >&2; exit 2 ;;
esac
