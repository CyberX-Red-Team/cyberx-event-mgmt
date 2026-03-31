#!/bin/bash
# Spin up the mock-redirector container, run SSH integration tests, then tear down.
#
# Usage:
#   cd backend
#   bash tests/docker/run_tests.sh
#
set -e

COMPOSE_FILE="tests/docker/docker-compose.test.yml"

echo "[*] Building and starting mock-redirector..."
docker compose -f "$COMPOSE_FILE" up -d --build

echo "[*] Waiting for SSH to be ready..."
for i in $(seq 1 15); do
    if ssh-keyscan -p 2222 localhost >/dev/null 2>&1; then
        echo "[+] SSH is ready."
        break
    fi
    if [ "$i" -eq 15 ]; then
        echo "[-] SSH not ready after 15 attempts. Aborting."
        docker compose -f "$COMPOSE_FILE" down
        exit 1
    fi
    sleep 1
done

# Copy the test private key from the container
echo "[*] Extracting test SSH key..."
docker compose -f "$COMPOSE_FILE" cp mock-redirector:/tmp/test_ssh_key /tmp/test_ssh_key
chmod 600 /tmp/test_ssh_key

echo "[*] Running integration tests..."
TEST_SSH_KEY_PATH=/tmp/test_ssh_key \
TEST_SSH_HOST=localhost \
TEST_SSH_PORT=2222 \
TEST_SSH_USER=cyberx \
DATABASE_URL="sqlite+aiosqlite:///:memory:" \
SECRET_KEY="test-secret" \
python -m pytest tests/integration/test_redirector_ssh.py -v -m ssh --tb=short "$@"

EXIT_CODE=$?

echo "[*] Tearing down..."
docker compose -f "$COMPOSE_FILE" down

exit $EXIT_CODE
