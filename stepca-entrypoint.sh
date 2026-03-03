#!/bin/sh
set -e

STEPPATH="${STEPPATH:-/home/step}"
CONFIG_DIR="${STEPPATH}/config"
CERTS_DIR="${STEPPATH}/certs"
SECRETS_DIR="${STEPPATH}/secrets"
CA_JSON="${CONFIG_DIR}/ca.json"
PASSWORD_FILE="${SECRETS_DIR}/password"

# step-ca listens on port 9000 by default
LISTEN_ADDRESS="${STEPCA_LISTEN_ADDRESS:-:9000}"
PROVISIONER_NAME="${STEPCA_PROVISIONER_NAME:-cyberx}"

echo "=== CyberX step-ca entrypoint ==="

# Ensure directories exist
mkdir -p "${CONFIG_DIR}" "${CERTS_DIR}" "${SECRETS_DIR}"

# Write provisioner password file
if [ -n "${STEPCA_PROVISIONER_PASSWORD}" ]; then
    echo "${STEPCA_PROVISIONER_PASSWORD}" > "${PASSWORD_FILE}"
    chmod 600 "${PASSWORD_FILE}"
else
    echo "ERROR: STEPCA_PROVISIONER_PASSWORD env var is required"
    exit 1
fi

# Check if CA files are provided via base64 env vars
# STEPCA_ROOT_CERT_B64: root CA cert (trust anchor)
# STEPCA_SIGNING_CERT_B64: the CA cert that will sign end-entity certs
# STEPCA_SIGNING_KEY_B64: its private key
if [ -z "${STEPCA_ROOT_CERT_B64}" ] || [ -z "${STEPCA_SIGNING_CERT_B64}" ] || [ -z "${STEPCA_SIGNING_KEY_B64}" ]; then
    echo "ERROR: Required env vars not set: STEPCA_ROOT_CERT_B64, STEPCA_SIGNING_CERT_B64, STEPCA_SIGNING_KEY_B64"
    exit 1
fi

# Phase 1: Initialize with throwaway CA if not already initialized
if [ ! -f "${CA_JSON}" ]; then
    echo ">>> Phase 1: Initializing step-ca with throwaway CA..."
    step ca init \
        --name="throwaway" \
        --provisioner="${PROVISIONER_NAME}" \
        --dns="localhost" \
        --address="${LISTEN_ADDRESS}" \
        --password-file="${PASSWORD_FILE}" \
        --provisioner-password-file="${PASSWORD_FILE}"
    echo ">>> Throwaway CA initialized"
else
    echo ">>> step-ca already initialized, skipping init"
fi

# Phase 2: Decode and replace CA files from base64 env vars
echo ">>> Phase 2: Importing CA files from environment..."

echo "${STEPCA_ROOT_CERT_B64}" | base64 -d > "${CERTS_DIR}/root_ca.crt"
echo "  - root_ca.crt written (trust anchor)"

echo "${STEPCA_SIGNING_CERT_B64}" | base64 -d > "${CERTS_DIR}/signing_ca.crt"
echo "  - signing_ca.crt written (signs end-entity certs)"

echo "${STEPCA_SIGNING_KEY_B64}" | base64 -d > "${SECRETS_DIR}/signing_ca_key"
chmod 600 "${SECRETS_DIR}/signing_ca_key"
echo "  - signing_ca_key written"

# Phase 3: Update ca.json to use imported CA files
echo ">>> Phase 3: Updating ca.json configuration..."

# Use step's built-in tool to get the fingerprint of the root cert
ROOT_FINGERPRINT=$(step certificate fingerprint "${CERTS_DIR}/root_ca.crt" 2>/dev/null || echo "")

# Build the ca.json with imported CA files
cat > "${CA_JSON}" << CAJSON
{
    "root": "${CERTS_DIR}/root_ca.crt",
    "federatedRoots": [],
    "crt": "${CERTS_DIR}/signing_ca.crt",
    "key": "${SECRETS_DIR}/signing_ca_key",
    "address": "${LISTEN_ADDRESS}",
    "insecureAddress": "",
    "dnsNames": ["localhost"],
    "logger": {"format": "text"},
    "db": {
        "type": "badgerv2",
        "dataSource": "${STEPPATH}/db",
        "badgerFileLoadingMode": ""
    },
    "authority": {
        "provisioners": [
            {
                "type": "JWK",
                "name": "${PROVISIONER_NAME}",
                "encryptedKey": "",
                "claims": {
                    "maxTLSCertDuration": "8760h",
                    "defaultTLSCertDuration": "2160h"
                }
            }
        ]
    },
    "tls": {
        "cipherSuites": [
            "TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256",
            "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256",
            "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256",
            "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384"
        ],
        "minVersion": 1.2,
        "maxVersion": 1.3,
        "renegotiation": false
    }
}
CAJSON

# Re-initialize the provisioner with the correct key
# step ca provisioner add will set up the JWK provisioner with the password
step ca provisioner remove "${PROVISIONER_NAME}" --type JWK 2>/dev/null || true
step ca provisioner add "${PROVISIONER_NAME}" --type JWK --create \
    --password-file="${PASSWORD_FILE}" 2>/dev/null || true

echo ">>> Configuration updated"

# Phase 4: Start step-ca
echo ">>> Phase 4: Starting step-ca on ${LISTEN_ADDRESS}..."
# Use full path — exec may fail on some runtimes due to capability inheritance
STEPCA_BIN=$(which step-ca 2>/dev/null || echo "/usr/local/bin/step-ca")
exec "${STEPCA_BIN}" "${CA_JSON}" --password-file="${PASSWORD_FILE}"
