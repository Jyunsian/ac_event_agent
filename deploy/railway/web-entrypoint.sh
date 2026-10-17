#!/bin/sh
set -eu
: "${WEB_AUTH_HTPASSWD:?Shared password hash required}"
: "${API_UPSTREAM:?Private API upstream required}"
: "${PORT:=8080}"
DNS_RESOLVERS=$(awk '/^nameserver / { if ($2 ~ /:/) printf "[%s] ", $2; else printf "%s ", $2 }' /etc/resolv.conf)
: "${DNS_RESOLVERS:?Container DNS resolver required}"
export PORT DNS_RESOLVERS
umask 077
printf '%s\n' "$WEB_AUTH_HTPASSWD" > /tmp/ac-event.htpasswd
envsubst '${PORT} ${API_UPSTREAM} ${DNS_RESOLVERS}' < /etc/nginx/ac-event.conf.template > /tmp/ac-event-nginx.conf
exec nginx -c /tmp/ac-event-nginx.conf -g 'daemon off;'
