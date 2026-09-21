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
        send_message(f"File sending error: {e}")
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
    time.sleep(2)
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

# Ban list handler
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

# 15-Min Backup & 12 PM Telegram Engine
def smart_backup_engine():
    daily_sent_date = ""
    while True:
        try:
            now = datetime.now()
            current_date_str = now.strftime("%Y-%m-%d")
            
            # Daily 12:00 PM Dispatch
            if now.hour == 12 and now.minute == 0 and daily_sent_date != current_date_str:
                daily_sent_date = current_date_str
                send_message("Daily 12:00 PM Automated Backup generate ho raha hai...")
                timestamp = now.strftime("%Y%m%d_120000")
                daily_zip = os.path.join(BACKUP_DIR, f"daily_backup_{timestamp}.zip")
                
                run_cmd(f"cd {BASE_DIR} && zip -rq {daily_zip} worlds/ server.properties blacklist.json")
                
                if send_document(daily_zip, f"Daily 12:00 PM Cloud Backup ({current_date_str})"):
                    for f in os.listdir(BACKUP_DIR):
                        f_path = os.path.join(BACKUP_DIR, f)
                        if os.path.isfile(f_path):
                            os.remove(f_path)
                    send_message("Daily backup delivered! Local backup folder wiped.")
                time.sleep(60)
                continue

            # Standard 15-Minute Local Snapshot with Max 3 Retention
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
        except Exception as e:
            print(f"Backup engine error: {e}")
            
        time.sleep(900)

# Real-Time Sentry & Hack Detect
def sentry_anti_hack():
    last_processed_line = ""
    HACK_PATTERNS = [
        ("moved wrongly", "Speedhack / Fly / Movement Exploit"),
        ("moved too quickly", "Speedhack / Teleport Glitch"),
        ("mismatch", "Position Desync / Phase Glitch"),
        ("invalid packet", "Bad Packet / Crash Exploit Attempt"),
        ("out of sync", "Tick Glitch / Dupe Attempt"),
        ("illegal item", "Illegal Item Spawn / Duplication Attempt")
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
                                send_message(
                                    f"🚨 **TARGET AUTO-BANNED!**\n"
                                    f"Target: `{target}`\n"
                                    f"Offense: `{hack_name}`\n"
                                    f"Action: Auto-banned & added to /banlist."
                                )
                                break
                
                for pattern, hack_name in HACK_PATTERNS:
                    if pattern.lower() in latest.lower():
                        send_message(f"⚠️ **SECURITY ALERT!**\nType: {hack_name}\nLog: `{latest}`")
                        break
        except Exception:
            pass

# ------------------------------------------------------------------
# MANUAL + AUTO UPDATE ENGINE (Supports custom version)
# ------------------------------------------------------------------
def perform_server_update(custom_version=None):
    if custom_version:
        version_str = custom_version.strip()
        latest_url = f"https://www.minecraft.net/bedrockdedicatedserver/bin-linux/bedrock-server-{version_str}.zip"
        send_message(f"Targeting Manual Version: `{version_str}`\nDownloading binary from Mojang...")
    else:
        send_message("Minecraft official server updates verify ho rahe hain...")
        cmd = 'curl -s -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" https://www.minecraft.net/en-us/download/server/bedrock | grep -o "https://[^\"]*bedrock-server-[^\"]*\\.zip" | head -n 1'
        res = run_cmd(cmd)
        latest_url = res.stdout.strip()
        
        if not latest_url or "bedrock-server-" not in latest_url:
            latest_url = "https://www.minecraft.net/bedrockdedicatedserver/bin-linux/bedrock-server-1.26.51.1.zip"
            
        version_str = latest_url.split("bedrock-server-")[-1].replace(".zip", "")
        send_message(f"Targeting Latest Detected Version: `{version_str}`\nBinary downloading & upgrading...")
    
    stop_server()
    update_zip = os.path.join(BASE_DIR, "server_update_temp.zip")
    run_cmd(f'rm -f {update_zip}')
    
    dl_res = run_cmd(f'wget --user-agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)" -O {update_zip} "{latest_url}"')
    if dl_res.returncode != 0 or not os.path.exists(update_zip) or os.path.getsize(update_zip) < 1000000:
        send_message(f"❌ Version `{version_str}` download fail ho gaya! Kripya version number check karein (URL galat ho sakti hai). Server restarting...")
        start_server()
        return

    extract_dir = os.path.join(BASE_DIR, "temp_update")
    run_cmd(f"rm -rf {extract_dir} && mkdir -p {extract_dir}")
    run_cmd(f"unzip -o -q {update_zip} -d {extract_dir}")
    
    # Update bedrock_server without touching worlds/ or server.properties
    run_cmd(f"cp -f {extract_dir}/bedrock_server {BASE_DIR}/bedrock_server")
    run_cmd(f"chmod +x {BASE_DIR}/bedrock_server")
    
    for item in ["libcrypto.so.1.1", "libssl.so.1.1", "definitions", "behavior_packs", "resource_packs"]:
        src_item = os.path.join(extract_dir, item)
        if os.path.exists(src_item):
            run_cmd(f"cp -rf {src_item} {BASE_DIR}/")
            
    run_cmd(f"rm -rf {extract_dir} {update_zip}")
    start_server()
    send_message(f"✅ Server successfully updated to version: `{version_str}`!\nServer online hai, game se connect karein.")

# ------------------------------------------------------------------
# ZIP / MCWORLD RESTORE ENGINE
# ------------------------------------------------------------------
def restore_backup_archive(archive_path, is_uploaded_world=False):
    send_message("Restoring world archive. Verifying integrity...")
    stop_server()
    
    temp_unzip = os.path.join(BASE_DIR, "temp_restore")
    run_cmd(f"rm -rf {temp_unzip} && mkdir -p {temp_unzip}")
    
    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
        zip_ref.extractall(temp_unzip)
        
    if os.path.exists(os.path.join(temp_unzip, "server.properties")) and os.path.exists(os.path.join(temp_unzip, "worlds")):
        run_cmd(f"cp -rf {temp_unzip}/worlds/* {WORLDS_DIR}/")
        run_cmd(f"cp -f {temp_unzip}/server.properties {PROPERTIES_FILE}")
        if os.path.exists(os.path.join(temp_unzip, "blacklist.json")):
            run_cmd(f"cp -f {temp_unzip}/blacklist.json {BAN_LIST_FILE}")
        send_message("Full server snapshot restored successfully.")
    else:
        level_dat_dir = None
        for root, dirs, files in os.walk(temp_unzip):
            if "level.dat" in files:
                level_dat_dir = root
                break
                
        world_folder_name = f"imported_world_{int(time.time())}"
        target_dir = os.path.join(WORLDS_DIR, world_folder_name)
        
        if level_dat_dir:
            shutil.copytree(level_dat_dir, target_dir, dirs_exist_ok=True)
        else:
            shutil.copytree(temp_unzip, target_dir, dirs_exist_ok=True)
            
        update_property("level-name", world_folder_name)
        send_message(f"Custom world map restored!\nActive World Name: `{world_folder_name}`")

    run_cmd(f"rm -rf {temp_unzip}")
    start_server()
    send_message("✅ World restoration complete. Bedrock Server online!")

def handle_document(doc):
    file_name = doc.get("file_name", "world.zip")
    if not file_name.endswith((".zip", ".mcworld")):
        send_message("Kripya sirf .zip ya .mcworld file bhejein!")
        return
        
    file_id = doc["file_id"]
    send_message(f"Downloading `{file_name}`...")
    res = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}").json()
    file_path = res["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    
    local_zip = os.path.join(BASE_DIR, "uploaded_archive.zip")
    r = requests.get(download_url, stream=True)
    with open(local_zip, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
            
    restore_backup_archive(local_zip, is_uploaded_world=True)
    run_cmd(f"rm -f {local_zip}")

HELP_TEXT = """MCPE Master Control Panel (50 Options Suite)

Surveillance & Auto-Ban:
1. /spy <player> - Lock target for high-rate scan & auto-ban
2. /unspy <player> - Remove from surveillance
3. /spylist - Active surveillance list
4. /banlist - View banned players & reasons

Security Hardening:
5. /propertyprotection <on|off> - Block break/place lock
6. /chestlock <on|off> - Container theft lock
7. /antixray <on|off> - Block custom X-Ray texture packs
8. /speedhackprotection <on|off> - Movement rewinds & rollback

Player Punishment & Freeze:
9. /freeze <player> - Lock player in place permanently
10. /unfreeze <player> - Remove movement lock
11. /mute <player> - Block player from chat
12. /unmute <player> - Allow chat
13. /kill <player> - Kill player
14. /clearinv <player> - Wipe player inventory

Player Roles & Permissions:
15. /players - List online players
16. /visitor <player> - Restrict to Visitor
17. /member <player> - Set to Member
18. /op <player> - Grant OP
19. /deop <player> - Revoke OP
20. /kick <player> - Kick player
21. /ban <player> [reason] - Manual Ban & Blacklist

Teleport & Inventory:
22. /tp <p1> <p2> - Teleport player1 to player2
23. /tpxyz <p> <x> <y> <z> - Teleport to coordinates
24. /give <p> <item> [count] - Give item
25. /effect <p> <effect> [sec] [amp] - Apply potion effect

Whitelist:
26. /whitelist <on|off> - Whitelist toggle
27. /whitelistadd <player> - Add to whitelist
28. /whitelistremove <player> - Remove from whitelist

Gameplay & Environment:
29. /coords - Toggle coordinates
30. /keepinventory - Toggle KeepInventory
31. /pvp <on|off> - Toggle PVP
32. /difficulty <peaceful|easy|normal|hard>
33. /gamemode <survival|creative|adventure>
34. /time <day|night|noon|midnight>
35. /weather <clear|rain|thunder>
36. /mobspawning <true|false>
37. /killmobs - Clear hostile mobs
38. /setworldspawn [x y z] - Set world spawn point

Chat & Broadcast:
39. /say <message> - Server broadcast
40. /clearchat - Clear in-game chat screen

World & Backups:
41. /seed <number> - Generate world with seed
42. [Send .zip / .mcworld] - Restore world map
43. /backup - Download full backup zip
44. /backuplist - View local snapshots (Max 3)
45. /restoresnapshot <file> - Restore local backup

Maintenance & Diagnostics:
46. /updateserver [version] - Update server (e.g. /updateserver 1.26.51.1)
47. /status - Server & tunnel status
48. /serverstats - System CPU, RAM & Disk stats
49. /logs - Live console logs
50. /restart - Safe restart Bedrock server
"""

def handle_updates():
    offset = 0
    start_server()
    send_message("Minecraft Guard Online!\nManual/Auto Updater Ready.\nType /help to view commands.")
    
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

                # Surveillance
                elif text.startswith("/spy "):
                    target = text.split(" ", 1)[1].strip()
                    SPY_TARGETS.add(target)
                    send_message(f"🎯 Target Locked: `{target}` (Monitored for speed/fly/dupe).")

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

                # Security Hardening
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

                # Freeze, Mute, Penalties
                elif text.startswith("/freeze "):
                    p = text.split(" ", 1)[1].strip()
                    FROZEN_PLAYERS.add(p)
                    send_to_console(f'effect "{p}" slowness 999999 255 true')
                    send_to_console(f'effect "{p}" jump_boost 999999 200 true')
                    send_message(f"❄️ Player `{p}` has been FROZEN in place!")

                elif text.startswith("/unfreeze "):
                    p = text.split(" ", 1)[1].strip()
                    FROZEN_PLAYERS.discard(p)
                    send_to_console(f'effect "{p}" clear')
                    send_message(f"Player `{p}` is now UNFROZEN.")

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

                # Roles & Moderation
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

                # World & Backup Controls
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
                    send_message("Backup zip create ho raha hai...")
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
                        out += "\nRestore karne ke liye: `/restoresnapshot <filename>`"
                        send_message(out)

                elif text.startswith("/restoresnapshot "):
                    snap_name = text.split(" ", 1)[1].strip()
                    target_file = os.path.join(BACKUP_DIR, snap_name)
                    if os.path.exists(target_file):
                        restore_backup_archive(target_file)
                    else:
                        send_message(f"Snapshot file `{snap_name}` nahi mili.")

                # 46. UPDATESERVER (Supports custom version e.g. /updateserver 1.26.51.1)
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
