# certs/ — repo-local TLS folder (NOT committed; test/bootstrap use only)

On 192.168.0.50 the reverse proxy uses the real certificate in **E:\certs**
(read-only bind mount), configured in `.env`:

    TLS_CERT_DIR=E:/certs
    TLS_CERT_FILE=mqtt.stormenergy.in-chain.pem
    TLS_KEY_FILE=mqtt.stormenergy.in-key.pem
    TLS_SERVER_NAME=mqtt.stormenergy.in

This repo-local folder is only used when `TLS_CERT_DIR=./certs`. If it holds no
certificate, `deploy.ps1` creates a **BOOTSTRAP / TEST self-signed** pair here
(`tls.crt` / `tls.key`, CN `storm-rtu-bootstrap-TEST-ONLY`) plus
`BOOTSTRAP-SELF-SIGNED.txt`. Browsers will warn about it.

Everything in this folder except this README is git-ignored. Never place a
production private key here.
