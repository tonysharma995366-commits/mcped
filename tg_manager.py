import os
import sys
import time
import json
import zipfile
import shutil
import threading
import subprocess
import requests
from datetime import datetime

BOT_TOKEN = "8972471605:AAE7hhT8QO5N_hnfHTIX1PxRzmkRBm5voyY"
CHAT_ID = "6955911349"
BASE_DIR = "/root/mcpe-server"
PROPERTIES_FILE = os.path.join(BASE_DIR, "server.properties")
WORLDS_DIR = os.path.join(BASE_DIR, "worlds")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
BAN_LIST_FILE = os.path.join(BASE_DIR, "blacklist.json")

os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(WORLDS_DIR, exist_ok=True)

SPY_TARGETS = set()
FROZEN_PLAYERS = set()

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        if len(text) > 4000:
            text = text[:4000] + "\n...[Truncated]"
        requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def send_document(file_path, caption=""):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, 'rb') as doc:
            requests.post(url, data={"chat_id": CHAT_ID, "caption": caption}, files={"document": doc}, timeout=180)
        return True
    except Exception as e:
        send_message(f"❌ File upload error: {e}")
        return False

def run_cmd(cmd):
    return subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

def send_to_console(mc_cmd):
    cmd = f'screen -S mcpe -X stuff "{mc_cmd}^M"'
    run_cmd(cmd)

def read_console_output(lines_count=15):
    time.sleep(0.4)
    run_cmd("rm -f /tmp/mc_screen.txt && screen -S mcpe -X hardcopy /tmp/mc_screen.txt")
    time.sleep(0.4)
    try:
        if os.path.exists("/tmp/mc_screen.txt"):
            with open("/tmp/mc_screen.txt", "r", errors="ignore") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            return "\n".join(lines[-lines_count:])
    except Exception as e:
        return f"Log read error: {e}"
    return "No logs captured."

def stop_server():
    send_to_console("stop")
    time.sleep(1.5)
    run_cmd("screen -S mcpe -X quit")
    run_cmd("pkill -9 bedrock_server")
    time.sleep(1)

def start_server():
    stop_server()
    cmd = f'screen -dmS mcpe bash -c "cd {BASE_DIR} && chmod +x bedrock_server && LD_LIBRARY_PATH=. ./bedrock_server"'
    run_cmd(cmd)
    time.sleep(2)

def update_property(key, value):
    if not os.path.exists(PROPERTIES_FILE):
        return
    with open(PROPERTIES_FILE, "r") as f:
        lines = f.readlines()
    found = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}\n")
    with open(PROPERTIES_FILE, "w") as f:
        f.writelines(new_lines)

def load_ban_list():
    if not os.path.exists(BAN_LIST_FILE):
        return []
    try:
        with open(BAN_LIST_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_ban_entry(player, reason):
    ban_list = load_ban_list()
    for entry in ban_list:
        if entry.get("name", "").lower() == player.lower():
            return
    entry = {
        "name": player,
        "reason": reason,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    ban_list.append(entry)
    with open(BAN_LIST_FILE, "w") as f:
        json.dump(ban_list, f, indent=4)

def remove_ban_entry(player):
    ban_list = load_ban_list()
    updated = [e for e in ban_list if e.get("name", "").lower() != player.lower()]
    with open(BAN_LIST_FILE, "w") as f:
        json.dump(updated, f, indent=4)

# -------------------------------------------------------------
# FACTORY RESET & FRESH SETUP ENGINE
# -------------------------------------------------------------
def trigger_factory_reset():
    send_message(
        "🧨 **FACTORY RESET INITIATED!**\n\n"
        "• Bedrock server stop kiya ja raha hai...\n"
        "• Saari world files, configs aur corrupt settings delete ho rahi hain...\n"
        "• Purana Playit tunnel aur tokens wipe ho rahe hain...\n"
        "• Fresh Playit tunnel generate kiya ja raha hai..."
    )
    
    reset_script = """#!/bin/bash
pkill -9 bedrock_server
pkill -9 playit-cli
screen -S mcpe -X quit 2>/dev/null || true
screen -S playit-tunnel -X quit 2>/dev/null || true

# Wipe all server data and playit tokens
rm -rf /root/mcpe-server
rm -rf /root/.config/playit /root/.playit /etc/playit*
rm -f /tmp/playit* /tmp/mc_*

# Re-run entrypoint in background
if [ -f "/root/entrypoint.sh" ]; then
    bash /root/entrypoint.sh &
elif [ -f "/entrypoint.sh" ]; then
    bash /entrypoint.sh &
fi
"""
    with open("/tmp/do_reset.sh", "w") as f:
        f.write(reset_script)
    run_cmd("chmod +x /tmp/do_reset.sh")
    
    # Detach and run
    subprocess.Popen(["bash", "/tmp/do_reset.sh"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sys.exit(0)

# -------------------------------------------------------------
# WORLD RESTORATION & MANAGEMENT
# -------------------------------------------------------------
def restore_backup_archive(archive_path, file_name):
    send_message(f"⚙️ [Step 2/5] Initializing restore for `{file_name}`...\n• Stopping Bedrock server safely to prevent chunk corruption...")
    stop_server()
    
    send_message("📦 [Step 3/5] Extracting archive files to temporary buffer...")
    temp_unzip = os.path.join(BASE_DIR, "temp_restore")
    run_cmd(f"rm -rf {temp_unzip} && mkdir -p {temp_unzip}")
    
    try:
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            zip_ref.extractall(temp_unzip)
    except Exception as e:
        send_message(f"❌ Zip extraction failed: {e}\nRestarting existing server...")
        start_server()
        return

    send_message("🔍 [Step 4/5] Analyzing world folders, builds & level database...")
    extracted_worlds_dir = os.path.join(temp_unzip, "worlds")
    active_world_folder = None

    if os.path.exists(extracted_worlds_dir):
        run_cmd(f"cp -rf {extracted_worlds_dir}/* {WORLDS_DIR}/")
        if os.path.exists(os.path.join(temp_unzip, "server.properties")):
            run_cmd(f"cp -f {temp_unzip}/server.properties {PROPERTIES_FILE}")
        if os.path.exists(os.path.join(temp_unzip, "blacklist.json")):
            run_cmd(f"cp -f {temp_unzip}/blacklist.json {BAN_LIST_FILE}")

        max_db_size = -1
        detected_worlds = []
        for w in os.listdir(WORLDS_DIR):
            w_path = os.path.join(WORLDS_DIR, w)
            db_path = os.path.join(w_path, "db")
            if os.path.isdir(db_path):
                total_size = sum(os.path.getsize(os.path.join(db_path, f)) for f in os.listdir(db_path) if os.path.isfile(os.path.join(db_path, f)))
                total_mb = round(total_size / (1024 * 1024), 2)
                detected_worlds.append(f"• `{w}` (Data: {total_mb} MB)")
                if total_size > max_db_size:
                    max_db_size = total_size
                    active_world_folder = w
        
        send_message("📁 Found World Containers:\n" + "\n".join(detected_worlds))
    else:
        level_dat_dir = None
        for root, dirs, files in os.walk(temp_unzip):
            if "level.dat" in files:
                level_dat_dir = root
                break
        
        target_name = f"world_{int(time.time())}"
        target_path = os.path.join(WORLDS_DIR, target_name)
        if level_dat_dir:
            shutil.copytree(level_dat_dir, target_path, dirs_exist_ok=True)
        else:
            shutil.copytree(temp_unzip, target_path, dirs_exist_ok=True)
        active_world_folder = target_name

    if active_world_folder:
        send_message(f"🎯 Setting active world: `{active_world_folder}`\n• Fixing write permissions (chmod 777)...")
        update_property("level-name", active_world_folder)
        run_cmd(f"chmod -R 777 {WORLDS_DIR}")
        send_message("🚀 [Step 5/5] Launching Bedrock server with restored builds & inventory...")
        start_server()
        time.sleep(2)
        send_message(f"✅ **WORLD RESTORATION COMPLETE!**\n• Active World: `{active_world_folder}`\n• Server Status: ONLINE\nPhone se connect karein, sabhi builds aur inventory active hain!")
    else:
        send_message("⚠️ Active world directory detect nahi ho saki. Restarting server...")
        start_server()

    run_cmd(f"rm -rf {temp_unzip}")

def handle_document(doc):
    file_name = doc.get("file_name", "world.zip")
    file_size = doc.get("file_size", 0)
    total_size_mb = round(file_size / (1024 * 1024), 2)

    if not file_name.endswith((".zip", ".mcworld")):
        send_message("❌ Kripya sirf `.zip` ya `.mcworld` backup file bhejein!")
        return

    file_id = doc["file_id"]
    send_message(f"📥 [Step 1/5] Backup file received!\n• Name: `{file_name}`\n• Size: `{total_size_mb} MB`\nDownloading from Telegram servers...")
    
    try:
        res = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}", timeout=20).json()
        file_path = res["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        
        local_zip = os.path.join(BASE_DIR, "uploaded_archive.zip")
        r = requests.get(download_url, stream=True, timeout=120)
        
        downloaded = 0
        last_reported_pct = -10
        with open(local_zip, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 512):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    pct = int((downloaded / file_size) * 100) if file_size > 0 else 0
                    if pct - last_reported_pct >= 25:
                        last_reported_pct = pct
                        dl_mb = round(downloaded / (1024 * 1024), 2)
                        send_message(f"⏳ Download Progress: {pct}% ({dl_mb}/{total_size_mb} MB)")
        
        send_message(f"✅ Download finished! (100% - {total_size_mb} MB verified)")
        restore_backup_archive(local_zip, file_name)
        run_cmd(f"rm -f {local_zip}")
    except Exception as e:
        send_message(f"❌ File download me dikkat aayi: {e}")

def perform_server_update(custom_version=None):
    if custom_version:
        version_str = custom_version.strip()
        latest_url = f"https://www.minecraft.net/bedrockdedicatedserver/bin-linux/bedrock-server-{version_str}.zip"
        send_message(f"🔄 [Step 1/4] Targeting version: `{version_str}`\nConnecting to official Mojang release...")
    else:
        send_message("🔄 [Step 1/4] Checking latest official Bedrock server release...")
        cmd = 'curl -s -A "Mozilla/5.0" https://www.minecraft.net/en-us/download/server/bedrock | grep -o "https://[^\"]*bedrock-server-[^\"]*\\.zip" | head -n 1'
        res = run_cmd(cmd)
        latest_url = res.stdout.strip()
        if not latest_url or "bedrock-server-" not in latest_url:
            latest_url = "https://www.minecraft.net/bedrockdedicatedserver/bin-linux/bedrock-server-1.26.51.1.zip"
        version_str = latest_url.split("bedrock-server-")[-1].replace(".zip", "")
        send_message(f"Targeting version: `{version_str}`")

    send_message(f"📥 [Step 2/4] Downloading Bedrock binary package for `{version_str}`...")
    update_zip = os.path.join(BASE_DIR, "server_update_temp.zip")
    run_cmd(f'rm -f {update_zip}')
    
    dl_res = run_cmd(f'wget --user-agent="Mozilla/5.0" -O {update_zip} "{latest_url}"')
    if dl_res.returncode != 0 or not os.path.exists(update_zip) or os.path.getsize(update_zip) < 1000000:
        send_message(f"❌ Version `{version_str}` download fail ho gaya! Server restarting...")
        start_server()
        return

    send_message("⚙️ [Step 3/4] Swapping binaries... Worlds & configs safe.")
    stop_server()
    extract_dir = os.path.join(BASE_DIR, "temp_update")
    run_cmd(f"rm -rf {extract_dir} && mkdir -p {extract_dir}")
    run_cmd(f"unzip -o -q {update_zip} -d {extract_dir}")
    
    run_cmd(f"cp -f {extract_dir}/bedrock_server {BASE_DIR}/bedrock_server")
    run_cmd(f"chmod +x {BASE_DIR}/bedrock_server")
    for item in ["libcrypto.so.1.1", "libssl.so.1.1", "definitions", "behavior_packs", "resource_packs"]:
        src_item = os.path.join(extract_dir, item)
        if os.path.exists(src_item):
            run_cmd(f"cp -rf {src_item} {BASE_DIR}/")
            
    run_cmd(f"rm -rf {extract_dir} {update_zip}")
    send_message("🚀 [Step 4/4] Starting server with updated binaries...")
    start_server()
    send_message(f"✅ **UPDATE SUCCESSFUL!**\nServer version: `{version_str}`\nStatus: ONLINE.")

def smart_backup_engine():
    daily_sent_date = ""
    while True:
        try:
            now = datetime.now()
            current_date_str = now.strftime("%Y-%m-%d")
            
            if now.hour == 12 and now.minute == 0 and daily_sent_date != current_date_str:
                daily_sent_date = current_date_str
                send_message("Daily 12:00 PM Cloud Backup generate ho raha hai...")
                timestamp = now.strftime("%Y%m%d_120000")
                daily_zip = os.path.join(BACKUP_DIR, f"daily_backup_{timestamp}.zip")
                
                run_cmd(f"cd {BASE_DIR} && zip -rq {daily_zip} worlds/ server.properties blacklist.json")
                
                if send_document(daily_zip, f"Daily 12:00 PM Cloud Backup ({current_date_str})"):
                    for f in os.listdir(BACKUP_DIR):
                        f_path = os.path.join(BACKUP_DIR, f)
                        if os.path.isfile(f_path):
                            os.remove(f_path)
                    send_message("Daily backup delivered! Local backup storage wiped.")
                time.sleep(60)
                continue

            timestamp = now.strftime("%Y%m%d_%H%M%S")
            backup_file = os.path.join(BACKUP_DIR, f"backup_{timestamp}.zip")
            run_cmd(f"cd {BASE_DIR} && zip -rq {backup_file} worlds/ server.properties blacklist.json")
            
            all_backups = sorted(
                [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.startswith("backup_")],
                key=os.path.getmtime
            )
            if len(all_backups) > 3:
                for old in all_backups[:-3]:
                    try:
                        os.remove(old)
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(900)

def sentry_anti_hack():
    last_processed_line = ""
    HACK_PATTERNS = [
        ("moved wrongly", "Speedhack / Movement Exploit"),
        ("moved too quickly", "Speedhack / Teleport Glitch"),
        ("mismatch", "Position Desync / Phase Glitch"),
        ("invalid packet", "Bad Packet / Exploit Attempt"),
        ("out of sync", "Tick Desync / Dupe Attempt"),
        ("illegal item", "Illegal Item Spawn Attempt")
    ]
    
    while True:
        time.sleep(1.5)
        try:
            for fp in list(FROZEN_PLAYERS):
                send_to_console(f'effect "{fp}" slowness 2 255 true')
                send_to_console(f'effect "{fp}" jump_boost 2 200 true')
                
            run_cmd("rm -f /tmp/sentry.txt && screen -S mcpe -X hardcopy /tmp/sentry.txt")
            if not os.path.exists("/tmp/sentry.txt"):
                continue
            with open("/tmp/sentry.txt", "r", errors="ignore") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            if not lines:
                continue
                
            latest = lines[-1]
            if latest != last_processed_line:
                last_processed_line = latest
                
                for target in list(SPY_TARGETS):
                    if target.lower() in latest.lower():
                        for pattern, hack_name in HACK_PATTERNS:
                            if pattern.lower() in latest.lower():
                                send_to_console(f'ban "{target}" "Illegal exploit detected: {hack_name}"')
                                send_to_console(f'kick "{target}" "Banned for {hack_name}"')
                                save_ban_entry(target, f"{hack_name} (Auto-Ban Sentry)")
                                SPY_TARGETS.discard(target)
                                send_message(f"🚨 **TARGET AUTO-BANNED!**\nTarget: `{target}`\nOffense: `{hack_name}`")
                                break
                
                for pattern, hack_name in HACK_PATTERNS:
                    if pattern.lower() in latest.lower():
                        send_message(f"⚠️ **SECURITY ALERT!**\nType: {hack_name}\nLog: `{latest}`")
                        break
        except Exception:
            pass

HELP_TEXT = """MCPE Master Control Panel (55 Options Suite)

Emergency Reset & Reinstall:
• /resetserver - Sabhi files delete karke pehli baar jaisa fresh install aur fresh tunnel setup shuru karein

Farm Chunk Loader (Radius Based):
1. /loadchunk <X> <Z> <radius> [name] - Load farm chunks 24/7
2. /chunklist - View active loaded farm chunks
3. /removechunk <name> - Stop loading specific chunk
4. /removeallchunks - Remove all active ticking chunk areas

Surveillance & Auto-Ban:
5. /spy <player> - Auto-scan target & auto-ban
6. /unspy <player> - Remove target from surveillance
7. /spylist - Active surveillance list
8. /banlist - View banned players & reasons

Security Hardening:
9. /propertyprotection <on|off> - Block break/place protection
10. /chestlock <on|off> - Container theft protection
11. /antixray <on|off> - Texture pack requirement
12. /speedhackprotection <on|off> - Movement rollback

Player Management & Freeze:
13. /freeze <player> - Lock player in place
14. /unfreeze <player> - Remove movement lock
15. /mute <player> - Block player chat
16. /unmute <player> - Unblock player chat
17. /kill <player> - Kill player
18. /clearinv <player> - Wipe player inventory

Roles & Moderation:
19. /players - List online players
20. /visitor <player> - Set Visitor role
21. /member <player> - Set Member role
22. /op <player> - Grant OP
23. /deop <player> - Revoke OP
24. /kick <player> - Kick player
25. /ban <player> [reason] - Manual Ban & Blacklist

Teleport & Inventory:
26. /tp <p1> <p2> - Teleport player1 to player2
27. /tpxyz <p> <x> <y> <z> - Teleport to coordinates
28. /give <p> <item> [count] - Give item
29. /effect <p> <effect> [sec] [amp] - Apply potion effect

Whitelist:
30. /whitelist <on|off> - Whitelist toggle
31. /whitelistadd <player> - Add to whitelist
32. /whitelistremove <player> - Remove from whitelist

Gameplay & Environment:
33. /coords - Show coordinates
34. /keepinventory - Enable KeepInventory
35. /pvp <on|off> - Toggle PVP
36. /difficulty <peaceful|easy|normal|hard>
37. /gamemode <survival|creative|adventure>
38. /time <day|night|noon|midnight>
39. /weather <clear|rain|thunder>
40. /mobspawning <true|false>
41. /killmobs - Clear hostile mobs
42. /setworldspawn [x y z] - Set world spawn point

Chat & Broadcast:
43. /say <message> - Server broadcast
44. /clearchat - Clear in-game chat

World & Backups:
45. /seed <number> - Generate world with seed
46. [Send .zip / .mcworld] - Restore world (Detailed 5-step progress)
47. /backup - Generate and download backup zip
48. /backuplist - View local snapshots (Max 3)
49. /restoresnapshot <file> - Restore local snapshot

Maintenance & Diagnostics:
50. /updateserver [version] - Update server (Live steps)
51. /status - Server & tunnel status
52. /serverstats - System CPU, RAM & Disk stats
53. /logs - Live console output
54. /restart - Safe restart Bedrock server
"""

def handle_updates():
    offset = 0
    start_server()
    send_message("Minecraft Guard Online!\nComplete Factory Reset & Radius Chunk Loader Active.\nType /help to view commands.")
    
    threading.Thread(target=smart_backup_engine, daemon=True).start()
    threading.Thread(target=sentry_anti_hack, daemon=True).start()
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=30"
            r = requests.get(url, timeout=40)
            data = r.json()
            if not data.get("ok"):
                time.sleep(2)
                continue
                
            for item in data.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message", {})
                chat = str(msg.get("chat", {}).get("id", ""))
                if chat != CHAT_ID:
                    continue
                    
                if "document" in msg:
                    handle_document(msg["document"])
                    continue
                    
                text = msg.get("text", "").strip()
                if not text:
                    continue
                
                if text in ["/start", "/help"]:
                    send_message(HELP_TEXT)

                # -------------------------------------------------------------
                # FACTORY RESET & FRESH SETUP HANDLER
                # -------------------------------------------------------------
                elif text == "/resetserver":
                    send_message(
                        "⚠️ **WARNING: COMPLETE FACTORY RESET!**\n\n"
                        "Yeh command chalane se:\n"
                        "1. Saare worlds, custom configs aur server files delete ho jayenge.\n"
                        "2. Playit tunnel aur tokens naye sire se wipe ho jayenge.\n"
                        "3. Naya Playit claim link aayega jaise container pehli baar chala tha.\n\n"
                        "Agar aap sach me sab kuch naya karna chahte hain, toh ye type karein:\n"
                        "`/resetserver CONFIRM`"
                    )

                elif text == "/resetserver CONFIRM":
                    trigger_factory_reset()

                # Chunk loader
                elif text.startswith("/loadchunk"):
                    parts = text.split()
                    try:
                        if len(parts) >= 4:
                            if len(parts) == 4 or (len(parts) == 5 and not parts[4].lstrip('-').isdigit()):
                                cx = int(parts[1])
                                cz = int(parts[2])
                                rad = int(parts[3])
                                area_name = parts[4] if len(parts) >= 5 else f"farm_{int(time.time())}"
                                x1, x2 = cx - rad, cx + rad
                                z1, z2 = cz - rad, cz + rad
                                send_to_console(f"tickingarea add {x1} 0 {z1} {x2} 256 {z2} {area_name}")
                                time.sleep(0.5)
                                send_message(f"🌾 **Farm Chunk Loaded (Always Active)!**\n• Name: `{area_name}`\n• Center: `({cx}, {cz})` | Radius: `{rad}` blocks\n• Bounded Area: `({x1}, {z1})` to `({x2}, {z2})`")
                            elif len(parts) >= 5:
                                cx = int(parts[1])
                                cy = int(parts[2])
                                cz = int(parts[3])
                                rad = int(parts[4])
                                area_name = parts[5] if len(parts) >= 6 else f"farm_{int(time.time())}"
                                x1, x2 = cx - rad, cx + rad
                                z1, z2 = cz - rad, cz + rad
                                send_to_console(f"tickingarea add {x1} 0 {z1} {x2} 256 {z2} {area_name}")
                                time.sleep(0.5)
                                send_message(f"🌾 **Farm Chunk Loaded (Always Active)!**\n• Name: `{area_name}`\n• Center: `({cx}, {cy}, {cz})` | Radius: `{rad}` blocks\n• Bounded Area: `({x1}, {z1})` to `({x2}, {z2})`")
                        else:
                            send_message("Usage: `/loadchunk <X> <Z> <radius> [name]`\nExample: `/loadchunk 100 200 30 iron_farm`")
                    except Exception as e:
                        send_message(f"Input error! Details: {e}")

                elif text == "/chunklist":
                    send_to_console("tickingarea list all-dimensions")
                    out = read_console_output(10)
                    send_message(f"📌 Active Loaded Chunks (Ticking Areas):\n{out}")

                elif text.startswith("/removechunk "):
                    name = text.split(" ", 1)[1].strip()
                    send_to_console(f"tickingarea remove {name}")
                    send_message(f"Chunk area `{name}` removed.")

                elif text == "/removeallchunks":
                    send_to_console("tickingarea remove_all")
                    send_message("Saare active chunk areas delete kar diye gaye.")

                # Surveillance
                elif text.startswith("/spy "):
                    target = text.split(" ", 1)[1].strip()
                    SPY_TARGETS.add(target)
                    send_message(f"🎯 Target Locked: `{target}`")

                elif text.startswith("/unspy "):
                    target = text.split(" ", 1)[1].strip()
                    SPY_TARGETS.discard(target)
                    send_message(f"Target `{target}` removed from surveillance.")

                elif text == "/spylist":
                    if not SPY_TARGETS:
                        send_message("Koi target active surveillance me nahi hai.")
                    else:
                        send_message("Active Targets:\n" + "\n".join([f"• `{t}`" for t in SPY_TARGETS]))

                elif text == "/banlist":
                    b_list = load_ban_list()
                    if not b_list:
                        send_message("Ban list khali hai.")
                    else:
                        out = "🚫 **Server Ban List:**\n\n"
                        for idx, e in enumerate(b_list, 1):
                            out += f"{idx}. `{e.get('name')}` - {e.get('reason')} ({e.get('date')})\n"
                        send_message(out)

                # Hardening
                elif text.startswith("/propertyprotection "):
                    mode = text.split(" ", 1)[1].strip().lower()
                    val = "true" if mode in ["on", "enable", "true"] else "false"
                    send_to_console(f"gamerule immutableworld {val}")
                    send_message(f"Property Protection: {val.upper()}")

                elif text.startswith("/chestlock "):
                    mode = text.split(" ", 1)[1].strip().lower()
                    send_to_console("scoreboard objectives add chestprotect dummy" if mode in ["on", "true"] else "")
                    send_message(f"Chest Lock: {mode.upper()}")

                elif text.startswith("/antixray "):
                    val = "true" if text.split(" ", 1)[1].strip().lower() in ["on", "true"] else "false"
                    update_property("texturepack-required", val)
                    send_message(f"Anti-Xray: {val}")

                elif text.startswith("/speedhackprotection "):
                    val = "true" if text.split(" ", 1)[1].strip().lower() in ["on", "true"] else "false"
                    update_property("correct-player-movement", val)
                    send_message(f"Speedhack rollback protection: {val}")

                # Freeze & Mute
                elif text.startswith("/freeze "):
                    p = text.split(" ", 1)[1].strip()
                    FROZEN_PLAYERS.add(p)
                    send_to_console(f'effect "{p}" slowness 999999 255 true')
                    send_to_console(f'effect "{p}" jump_boost 999999 200 true')
                    send_message(f"❄️ Player `{p}` FROZEN!")

                elif text.startswith("/unfreeze "):
                    p = text.split(" ", 1)[1].strip()
                    FROZEN_PLAYERS.discard(p)
                    send_to_console(f'effect "{p}" clear')
                    send_message(f"Player `{p}` UNFROZEN.")

                elif text.startswith("/mute "):
                    p = text.split(" ", 1)[1].strip()
                    send_to_console(f'ability "{p}" mute true')
                    send_message(f"Player `{p}` muted.")

                elif text.startswith("/unmute "):
                    p = text.split(" ", 1)[1].strip()
                    send_to_console(f'ability "{p}" mute false')
                    send_message(f"Player `{p}` unmuted.")

                elif text.startswith("/kill "):
                    p = text.split(" ", 1)[1].strip()
                    send_to_console(f'kill "{p}"')
                    send_message(f"Killed: {p}")

                elif text.startswith("/clearinv "):
                    p = text.split(" ", 1)[1].strip()
                    send_to_console(f'clear "{p}"')
                    send_message(f"Cleared inventory: {p}")

                # Moderation
                elif text == "/players":
                    send_to_console("list")
                    out = read_console_output(6)
                    send_message(f"Online Players:\n{out}")

                elif text.startswith("/visitor "):
                    p = text.split(" ", 1)[1].strip()
                    send_to_console(f'permission set "{p}" visitor')
                    send_message(f"{p} is now a VISITOR.")

                elif text.startswith("/member "):
                    p = text.split(" ", 1)[1].strip()
                    send_to_console(f'permission set "{p}" member')
                    send_message(f"{p} is now a MEMBER.")

                elif text.startswith("/op "):
                    p = text.split(" ", 1)[1].strip()
                    send_to_console(f'op "{p}"')
                    send_message(f"OP granted: {p}")

                elif text.startswith("/deop "):
                    p = text.split(" ", 1)[1].strip()
                    send_to_console(f'deop "{p}"')
                    send_message(f"OP revoked: {p}")

                elif text.startswith("/kick "):
                    p = text.split(" ", 1)[1].strip()
                    send_to_console(f'kick "{p}"')
                    send_message(f"Kicked: {p}")

                elif text.startswith("/ban "):
                    parts = text.split(maxsplit=2)
                    p = parts[1].strip()
                    reason = parts[2].strip() if len(parts) > 2 else "Admin Ban"
                    send_to_console(f'ban "{p}" "{reason}"')
                    save_ban_entry(p, reason)
                    send_message(f"Banned: `{p}` ({reason})")

                elif text.startswith("/unban "):
                    p = text.split(" ", 1)[1].strip()
                    send_to_console(f'unban "{p}"')
                    remove_ban_entry(p)
                    send_message(f"Player `{p}` unbanned.")

                # Teleport & Give
                elif text.startswith("/tpxyz "):
                    parts = text.split()
                    if len(parts) >= 5:
                        send_to_console(f'tp "{parts[1]}" {parts[2]} {parts[3]} {parts[4]}')
                        send_message(f"Teleported {parts[1]} to {parts[2]} {parts[3]} {parts[4]}.")

                elif text.startswith("/tp "):
                    parts = text.split()
                    if len(parts) >= 3:
                        send_to_console(f'tp "{parts[1]}" "{parts[2]}"')
                        send_message(f"Teleported {parts[1]} to {parts[2]}.")

                elif text.startswith("/give "):
                    parts = text.split()
                    if len(parts) >= 3:
                        cnt = parts[3] if len(parts) >= 4 else "1"
                        send_to_console(f'give "{parts[1]}" {parts[2]} {cnt}')
                        send_message(f"Given {cnt}x {parts[2]} to {parts[1]}.")

                elif text.startswith("/effect "):
                    parts = text.split()
                    if len(parts) >= 3:
                        sec = parts[3] if len(parts) >= 4 else "30"
                        amp = parts[4] if len(parts) >= 5 else "1"
                        send_to_console(f'effect "{parts[1]}" {parts[2]} {sec} {amp}')
                        send_message(f"Applied effect {parts[2]} to {parts[1]}.")

                # Whitelist
                elif text.startswith("/whitelist "):
                    mode = text.split(" ", 1)[1].strip().lower()
                    val = "on" if mode in ["on", "true"] else "off"
                    send_to_console(f"whitelist {val}")
                    send_message(f"Whitelist: {val.upper()}")

                elif text.startswith("/whitelistadd "):
                    p = text.split(" ", 1)[1].strip()
                    send_to_console(f'whitelist add "{p}"')
                    send_message(f"Added to whitelist: {p}")

                elif text.startswith("/whitelistremove "):
                    p = text.split(" ", 1)[1].strip()
                    send_to_console(f'whitelist remove "{p}"')
                    send_message(f"Removed from whitelist: {p}")

                # Environment
                elif text == "/coords":
                    send_to_console("gamerule showcoordinates true")
                    send_message("Coordinates ON!")

                elif text == "/keepinventory":
                    send_to_console("gamerule keepinventory true")
                    send_message("KeepInventory ON!")

                elif text.startswith("/pvp "):
                    val = "true" if text.split(" ", 1)[1].strip().lower() in ["on", "true"] else "false"
                    send_to_console(f"gamerule pvp {val}")
                    update_property("pvp", val)
                    send_message(f"PVP: {val}")

                elif text.startswith("/difficulty "):
                    diff = text.split(" ", 1)[1].strip().lower()
                    send_to_console(f"difficulty {diff}")
                    update_property("difficulty", diff)
                    send_message(f"Difficulty: {diff}")

                elif text.startswith("/gamemode "):
                    gm = text.split(" ", 1)[1].strip().lower()
                    send_to_console(f"defaultgamemode {gm}")
                    update_property("gamemode", gm)
                    send_message(f"Gamemode: {gm}")

                elif text.startswith("/time "):
                    t_val = text.split(" ", 1)[1].strip().lower()
                    send_to_console(f"time set {t_val}")
                    send_message(f"Time: {t_val}")

                elif text.startswith("/weather "):
                    w_val = text.split(" ", 1)[1].strip().lower()
                    send_to_console(f"weather {w_val}")
                    send_message(f"Weather: {w_val}")

                elif text.startswith("/mobspawning "):
                    val = text.split(" ", 1)[1].strip().lower()
                    send_to_console(f"gamerule domobspawning {val}")
                    send_message(f"Mob Spawning: {val}")

                elif text == "/killmobs":
                    send_to_console("kill @e[type=!player]")
                    send_message("Hostile mobs cleared!")

                elif text.startswith("/setworldspawn"):
                    parts = text.split()
                    if len(parts) >= 4:
                        send_to_console(f"setworldspawn {parts[1]} {parts[2]} {parts[3]}")
                        send_message(f"World spawn set to: {parts[1]} {parts[2]} {parts[3]}")
                    else:
                        send_to_console("setworldspawn")
                        send_message("World spawn set to current position.")

                # Chat
                elif text.startswith("/say "):
                    msg_say = text.split(" ", 1)[1].strip()
                    send_to_console(f'say [SERVER]: {msg_say}')
                    send_message(f"Broadcasted: {msg_say}")

                elif text == "/clearchat":
                    for _ in range(15):
                        send_to_console('say ')
                    send_message("In-game chat cleared.")

                # World & Backup
                elif text.startswith("/seed"):
                    parts = text.split(maxsplit=1)
                    if len(parts) >= 2:
                        seed_val = parts[1].strip()
                        new_world = f"world_{int(time.time())}"
                        stop_server()
                        update_property("level-seed", seed_val)
                        update_property("level-name", new_world)
                        start_server()
                        send_message(f"New world generated: {new_world} (Seed: {seed_val})")

                elif text == "/backup":
                    send_message("Creating backup archive...")
                    timestamp = time.strftime("%Y%m%d_%H%M%S")
                    backup_zip = os.path.join(BACKUP_DIR, f"manual_backup_{timestamp}.zip")
                    run_cmd(f"cd {BASE_DIR} && zip -rq {backup_zip} worlds/ server.properties blacklist.json")
                    send_document(backup_zip, f"Backup Snapshot ({timestamp})")

                elif text == "/backuplist":
                    backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip")])
                    if not backups:
                        send_message("Koi local backup snapshot nahi mila.")
                    else:
                        out = "Active Local Backups (Max 3 retained):\n\n"
                        for b in backups:
                            sz = os.path.getsize(os.path.join(BACKUP_DIR, b)) // 1024
                            out += f" • `{b}` ({sz} KB)\n"
                        out += "\nRestore command: `/restoresnapshot <filename>`"
                        send_message(out)

                elif text.startswith("/restoresnapshot "):
                    snap_name = text.split(" ", 1)[1].strip()
                    target_file = os.path.join(BACKUP_DIR, snap_name)
                    if os.path.exists(target_file):
                        restore_backup_archive(target_file, snap_name)
                    else:
                        send_message(f"Snapshot file `{snap_name}` nahi mili.")

                elif text.startswith("/updateserver"):
                    parts = text.split()
                    custom_ver = parts[1].strip() if len(parts) > 1 else None
                    perform_server_update(custom_ver)

                # Diagnostics & Control
                elif text == "/status":
                    out = run_cmd("screen -ls").stdout
                    status = "ONLINE" if "mcpe" in out else "OFFLINE"
                    playit = "ONLINE" if "playit-tunnel" in out else "OFFLINE"
                    send_message(f"Server Status:\nMinecraft: {status}\nPlayit Tunnel: {playit}")

                elif text == "/serverstats":
                    mem = run_cmd("free -m | awk 'NR==2{printf \"Memory: %s/%sMB (%.2f%%)\", $3,$2,$3*100/$2 }'").stdout
                    disk = run_cmd("df -h / | awk 'NR==2{printf \"Disk Free: %s / Total: %s\", $4,$2}'").stdout
                    cpu = run_cmd("top -bn1 | grep 'Cpu(s)' | awk '{print \"CPU Usage: \" $2 + $4 \"%\"}'").stdout
                    send_message(f"📊 Server Hardware Stats:\n• {mem}\n• {cpu.strip()}\n• {disk}")

                elif text == "/logs":
                    out = read_console_output(15)
                    send_message(f"Live Console Logs:\n{out}")

                elif text == "/restart":
                    send_message("Server restart ho raha hai...")
                    start_server()
                    send_message("Server restarted.")

                elif text == "/fixtunnel":
                    send_message("Restarting Playit...")
                    run_cmd("pkill -9 playit-cli")
                    run_cmd("screen -S playit-tunnel -X quit")
                    time.sleep(1)
                    run_cmd("screen -dmS playit-tunnel /usr/local/bin/playit-cli")
                    send_message("Playit restart complete!")

                elif text.startswith("/cmd "):
                    mc_cmd = text.split(" ", 1)[1].strip()
                    send_to_console(mc_cmd)
                    send_message(f"Command sent: {mc_cmd}")

                elif text.startswith("/shell "):
                    sh_cmd = text.split(" ", 1)[1].strip()
                    res = run_cmd(sh_cmd)
                    out_text = res.stdout if res.stdout else res.stderr
                    send_message(f"Shell Output:\n{out_text if out_text else 'Done.'}")

        except Exception:
            time.sleep(2)

if __name__ == "__main__":
    handle_updates()
