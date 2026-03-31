FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    nginx \
    libnginx-mod-stream \
    sudo \
    procps \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Create the cyberx test user
RUN useradd -m -s /bin/bash cyberx \
    && echo "cyberx:cyberx" | chpasswd

# Grant sudo for nginx operations (matches production sudoers pattern)
RUN echo "cyberx ALL=(ALL) NOPASSWD: /usr/sbin/nginx, /bin/systemctl reload nginx, /bin/systemctl restart nginx, /bin/cp, /bin/bash" \
    > /etc/sudoers.d/cyberx \
    && chmod 440 /etc/sudoers.d/cyberx

# Set up SSH directory for cyberx
RUN mkdir -p /home/cyberx/.ssh \
    && chmod 700 /home/cyberx/.ssh \
    && chown -R cyberx:cyberx /home/cyberx/.ssh

# Generate a test SSH host key
RUN ssh-keygen -A

# Configure SSHD
RUN mkdir -p /run/sshd \
    && sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config \
    && sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config

# Set up nginx stream directory
RUN mkdir -p /etc/nginx/stream.d \
    && chown cyberx:cyberx /etc/nginx/stream.d

# Add stream include to nginx.conf
RUN echo 'stream { include /etc/nginx/stream.d/*.conf; }' >> /etc/nginx/nginx.conf

# Remove default site to avoid port 80 conflict
RUN rm -f /etc/nginx/sites-enabled/default

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22

ENTRYPOINT ["/entrypoint.sh"]
