#!/bin/sh
set -eu
TARGET="/etc/nginx/conf.d/default.conf"
if [ -z "${BACKEND_FQDN:-}" ] || [ "$BACKEND_FQDN" = "REPLACE_ME_ON_DEPLOYMENT" ]; then
  echo "ERROR: set BACKEND_FQDN to the backend ingress FQDN (hostname only)." >&2
  exit 1
fi
sed "s#__BACKEND_FQDN__#${BACKEND_FQDN}#g" /default.confACA.template > "$TARGET"
exec nginx -g "daemon off;"
