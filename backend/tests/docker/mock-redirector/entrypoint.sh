#!/bin/bash
set -e

# Generate test SSH key pair if not already present
if [ ! -f /home/cyberx/.ssh/id_ed25519 ]; then
    ssh-keygen -t ed25519 -f /home/cyberx/.ssh/id_ed25519 -N "" -C "cyberx-test"
    cat /home/cyberx/.ssh/id_ed25519.pub >> /home/cyberx/.ssh/authorized_keys
    chmod 600 /home/cyberx/.ssh/authorized_keys
    chown -R cyberx:cyberx /home/cyberx/.ssh
fi

# Export the private key so tests can read it from a known location
cp /home/cyberx/.ssh/id_ed25519 /tmp/test_ssh_key
chmod 644 /tmp/test_ssh_key

# Start nginx (non-daemon for status checks but backgrounded)
nginx &

# Start SSH daemon in foreground
exec /usr/sbin/sshd -D -e
