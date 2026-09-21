FROM --platform=linux/amd64 ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Core utilities, dependencies, and GUI
RUN apt update -y && apt install --no-install-recommends -y \
    xfce4 tigervnc-standalone-server novnc websockify \
    sudo xterm curl wget git tzdata \
    dbus-x11 x11-utils x11-xserver-utils x11-apps \
    python3 python3-requests unzip screen libcurl4 zip ca-certificates jq \
    && rm -rf /var/lib/apt/lists/*

RUN touch /root/.Xauthority

# Install Playit CLI binary for tunneling
RUN curl -SsL https://github.com/playit-cloud/playit-agent/releases/download/v0.15.26/playit-linux-amd64 -o /usr/local/bin/playit-cli && \
    chmod +x /usr/local/bin/playit-cli

# Copy configuration scripts
COPY entrypoint.sh /root/entrypoint.sh
COPY tg_manager.py /root/tg_manager.py

# Make entrypoint executable
RUN chmod +x /root/entrypoint.sh

WORKDIR /root
EXPOSE 5901
EXPOSE 6080

CMD ["/bin/bash", "/root/entrypoint.sh"]
