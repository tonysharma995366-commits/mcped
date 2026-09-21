#!/bin/bash

# 1. Setup VNC & noVNC Web GUI for backend monitoring
vncserver -localhost no -SecurityTypes None -geometry 1024x768 --I-KNOW-THIS-IS-INSECURE
openssl req -new -subj "/C=JP" -x509 -days 365 -nodes -out /root/self.pem -keyout /root/self.pem
websockify -D --web=/usr/share/novnc/ --cert=/root/self.pem 6080 localhost:5901

BOT_TOKEN="8972471605:AAE7hhT8QO5N_hnfHTIX1PxRzmkRBm5voyY"
CHAT_ID="6955911349"
SERVER_DIR="/root/mcpe-server"

send_tg() {
    local text="$1"
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${CHAT_ID}" \
        -d "text=${text}" > /dev/null
}

(
    # 2. Launch Playit to get Tunnel Info
    rm -f /tmp/playit_output.log
    /usr/local/bin/playit-cli > /tmp/playit_output.log 2>&1 &
    PLAYIT_PID=$!

    CLAIM_URL=""
    for i in {1..30}; do
        if grep -q "playit.gg/claim/" /tmp/playit_output.log; then
            CLAIM_URL=$(grep -o 'https://playit.gg/claim/[a-zA-Z0-9]*' /tmp/playit_output.log | head -n 1)
            break
        fi
        sleep 1
    done

    if [ -n "$CLAIM_URL" ]; then
        send_tg "Minecraft Core Init!
Claim Playit Tunnel:
$CLAIM_URL

Protocol: Minecraft Bedrock (UDP)
Port: 19132

Claim karne ke baad bot ko 'done' likhkar bhejein."
    else
        send_tg "Playit tunnel active. Verifying server files..."
    fi

    # 3. Wait for Telegram Confirmation ('done' or 'ready')
    LAST_UPDATE_ID=$(curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getUpdates" | grep -o '"update_id":[0-9]*' | tail -n 1 | cut -d: -f2)
    [ -z "$LAST_UPDATE_ID" ] && LAST_UPDATE_ID=0

    CONFIRMED=false
    while [ "$CONFIRMED" = false ]; do
        UPDATES=$(curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getUpdates?offset=$((LAST_UPDATE_ID + 1))")
        if echo "$UPDATES" | grep -q '"text"'; then
            MSG=$(echo "$UPDATES" | grep -o '"text":"[^"]*"' | tail -n 1 | cut -d'"' -f4 | tr '[:upper:]' '[:lower:]')
            NEW_ID=$(echo "$UPDATES" | grep -o '"update_id":[0-9]*' | tail -n 1 | cut -d: -f2)
            LAST_UPDATE_ID=$NEW_ID
            
            if [[ "$MSG" =~ ^(done|ok|yes|ready|ho gaya|ban gaya)$ ]]; then
                CONFIRMED=true
                send_tg "Confirmation received! Downloading latest secure Mojang binary..."
                break
            fi
        fi
        sleep 3
    done

    # 4. Stop initial Playit check to launch properly in screen later
    kill $PLAYIT_PID 2>/dev/null || true
    sleep 2

    # 5. Build Server Directory Structure
    mkdir -p "$SERVER_DIR"
    mkdir -p "$SERVER_DIR/backups"
    cd "$SERVER_DIR"

    # Fetch latest official server binary on first boot
    if [ ! -f "bedrock_server" ]; then
        LATEST_ZIP_URL=$(curl -s -H "User-Agent: Mozilla/5.0 (X11; Linux x86_64)" https://www.minecraft.net/en-us/download/server/bedrock | grep -o 'https://www.minecraft.net/bedrockdedicatedserver/bin-linux/bedrock-server-[^"]*\.zip' | head -n 1)
        if [ -z "$LATEST_ZIP_URL" ]; then
            # Fail-safe URL
            LATEST_ZIP_URL="https://www.minecraft.net/bedrockdedicatedserver/bin-linux/bedrock-server-1.21.0.03.zip"
        fi
        wget --user-agent="Mozilla/5.0" -O bedrock-server-latest.zip "$LATEST_ZIP_URL"
        unzip -o -q bedrock-server-latest.zip
        chmod +x bedrock_server
    fi

    # Create empty blacklist if not exists
    if [ ! -f "blacklist.json" ]; then
        echo "[]" > blacklist.json
    fi

    # 6. Apply Default Ironclad Security Properties
    sed -i 's/texturepack-required=.*/texturepack-required=true/g' server.properties 2>/dev/null || echo "texturepack-required=true" >> server.properties
    sed -i 's/correct-player-movement=.*/correct-player-movement=true/g' server.properties 2>/dev/null || echo "correct-player-movement=true" >> server.properties
    sed -i 's/server-authoritative-movement=.*/server-authoritative-movement=server-auth-with-rewind/g' server.properties 2>/dev/null || echo "server-authoritative-movement=server-auth-with-rewind" >> server.properties
    sed -i 's/allow-cheats=.*/allow-cheats=false/g' server.properties 2>/dev/null || echo "allow-cheats=false" >> server.properties
    sed -i 's/default-player-permission-level=.*/default-player-permission-level=member/g' server.properties 2>/dev/null || echo "default-player-permission-level=member" >> server.properties
    sed -i 's/allow-list=.*/allow-list=false/g' server.properties 2>/dev/null || echo "allow-list=false" >> server.properties
    sed -i 's/white-list=.*/white-list=false/g' server.properties 2>/dev/null || echo "white-list=false" >> server.properties

    # 7. Start Permanent Services in Background (Screen)
    screen -dmS playit-tunnel /usr/local/bin/playit-cli
    screen -dmS tg-bot python3 /root/tg_manager.py

    send_tg "Setup Complete! 50-Options Control Panel is Online. Type /help in bot to begin."
) &

# Keep container alive
tail -f /dev/null
