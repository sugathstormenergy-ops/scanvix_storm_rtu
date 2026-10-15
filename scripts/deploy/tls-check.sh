#!/bin/sh
# Storm Energy RTU - read-only TLS material validation (runs in a throwaway
# alpine container; the certificate directory is mounted READ-ONLY at /certs).
# Prints KEY=VALUE lines parsed by deploy.ps1. Never prints private key material.
# Inputs (env): STORM_TLS_CERT_FILE, STORM_TLS_KEY_FILE, STORM_TLS_HOST (optional)
set -u
apk add --no-cache openssl >/dev/null 2>&1 || { echo "ERROR=openssl-install-failed"; exit 20; }
C="/certs/${STORM_TLS_CERT_FILE}"
K="/certs/${STORM_TLS_KEY_FILE}"
[ -f "$C" ] || { echo "ERROR=certificate-file-not-found"; exit 10; }
[ -f "$K" ] || { echo "ERROR=key-file-not-found"; exit 11; }

W=$(mktemp -d)
tr -d '\r' < "$C" > "$W/all.pem"
awk -v d="$W" '/-----BEGIN CERTIFICATE-----/{n++} n{print > (d "/c" n ".pem")}' "$W/all.pem"
N=$(grep -c -- '-----BEGIN CERTIFICATE-----' "$W/all.pem")
[ "$N" -ge 1 ] || { echo "ERROR=no-certificate-in-file"; exit 12; }

echo "SUBJECT=$(openssl x509 -in "$W/c1.pem" -noout -subject | sed 's/^subject=//')"
echo "ISSUER=$(openssl x509 -in "$W/c1.pem" -noout -issuer | sed 's/^issuer=//')"
echo "NOTAFTER=$(openssl x509 -in "$W/c1.pem" -noout -enddate | sed 's/^notAfter=//')"
echo "SAN=$(openssl x509 -in "$W/c1.pem" -noout -ext subjectAltName 2>/dev/null | tail -n +2 | tr -d ' \n')"
echo "CHAIN_CERTS=$N"
if openssl x509 -in "$W/c1.pem" -noout -checkend 0 >/dev/null; then echo "EXPIRED=no"; else echo "EXPIRED=yes"; fi
if openssl x509 -in "$W/c1.pem" -noout -checkend 1209600 >/dev/null; then echo "EXPIRES_14D=no"; else echo "EXPIRES_14D=yes"; fi
if [ -n "${STORM_TLS_HOST:-}" ]; then
    if openssl x509 -in "$W/c1.pem" -noout -checkhost "$STORM_TLS_HOST" | grep -q 'does match'; then echo "HOST_MATCH=yes"; else echo "HOST_MATCH=no"; fi
fi
KP=$(openssl pkey -passin pass: -in "$K" -pubout 2>/dev/null | sha256sum | cut -d' ' -f1)
CP=$(openssl x509 -in "$W/c1.pem" -noout -pubkey | sha256sum | cut -d' ' -f1)
EMPTY=$(printf '' | sha256sum | cut -d' ' -f1)
if [ "$KP" = "$EMPTY" ]; then echo "KEY_MATCH=unreadable-or-encrypted"
elif [ "$KP" = "$CP" ]; then echo "KEY_MATCH=yes"
else echo "KEY_MATCH=no"; fi
: > "$W/untrusted.pem"
i=2; while [ "$i" -le "$N" ]; do cat "$W/c$i.pem" >> "$W/untrusted.pem"; i=$((i+1)); done
if [ "$N" -ge 2 ]; then V=$(openssl verify -untrusted "$W/untrusted.pem" "$W/c1.pem" 2>&1 | tail -1)
else V=$(openssl verify "$W/c1.pem" 2>&1 | tail -1); fi
case "$V" in *": OK") echo "CHAIN_VERIFY=ok" ;; *) echo "CHAIN_VERIFY=failed:$(echo "$V" | tr ' ' '_')" ;; esac
rm -rf "$W"
exit 0
