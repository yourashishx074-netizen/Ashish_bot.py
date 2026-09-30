import asyncio
import re
import random
import os
from aiohttp import web
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

# ===== RENDER ENVIRONMENT VARIABLES SE UTHAYEGA =====
api_id = int(os.environ.get("API_ID", "36055068"))
api_hash = os.environ.get("API_HASH", "e62c399663de4721efb786f7cfc64022")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
# ====================================================

bot = TelegramClient("bot_session", api_id, api_hash)
active_users = {}

def is_valid_text_message(msg):
    if not msg or not msg.raw_text or msg.sticker or msg.photo or msg.video or msg.document:
        return False
    text = msg.raw_text.strip()
    if re.fullmatch(r"[\.\s\-_,]+", text):
        return False
    emoji_cleaned = re.sub(
        r"[\U00010000-\U0010ffff\u2600-\u27ff\u2300-\u23ff\u2b50\u200d\ufe0f\s]+",
        "",
        text
    )
    if not emoji_cleaned:
        return False
    return True

async def get_best_available_target_message(user_client, chat_id, target_sender_id, session_obj):
    live_id = session_obj.get("latest_target_msg_id")
    if live_id:
        try:
            chk = await user_client.get_messages(chat_id, ids=live_id)
            if chk and is_valid_text_message(chk):
                return live_id
        except Exception:
            pass

    try:
        async for msg in user_client.iter_messages(chat_id, limit=30, from_user=target_sender_id):
            if is_valid_text_message(msg):
                session_obj["latest_target_msg_id"] = msg.id
                return msg.id
    except Exception:
        pass
    return None

def get_delay(u_data, task_type):
    current_speed_mode = u_data.get("current_speed_mode", "hard")
    custom_delay_seconds = u_data.get("custom_delay_seconds", 2.0)
    
    if current_speed_mode == "custom":
        return custom_delay_seconds
    elif current_speed_mode == "ultra":
        return 0.05 if task_type == "oneword" else 0.3
    elif current_speed_mode == "hard":
        if task_type in ["cp", "bot"]:
            return random.uniform(2.0, 3.0)
        elif task_type == "oneword":
            return 0.15
        else:
            return 1.5
    elif current_speed_mode == "medium":
        if task_type in ["cp", "bot"]:
            return random.uniform(3.0, 4.0)
        elif task_type == "oneword":
            return 0.4
        else:
            return random.uniform(4.0, 5.0)
    return 0.15 if task_type == "oneword" else 1.5

@bot.on(events.NewMessage(pattern=r"^/start$"))
async def start_cmd(event):
    if not event.is_private:
        return
    await event.respond("👋 Welcome! Bot is active and running.\nUserbot login karne ke liye `/add` bhejein.")

@bot.on(events.NewMessage(pattern=r"^/add$"))
async def add_userbot_cmd(event):
    if not event.is_private:
        return
    user_id = event.sender_id
    if user_id in active_users and active_users[user_id].get("client") and active_users[user_id]["client"].is_connected():
        await event.respond("✅ Aapka userbot already logged in hai!\nLogout karne ke liye `/logout` bhejein.")
        return

    active_users[user_id] = {
        "state": "waiting_phone",
        "phone_number": None,
        "temp_client": None,
        "phone_code_hash": None,
        "client": None,
        "current_speed_mode": "hard",
        "custom_delay_seconds": 2.0,
        "cp_responses": [],
        "cp_index": 0,
        "bot_responses": [],
        "bot_index": 0,
        "zinda_responses": [],
        "zinda_index": 0,
        "raid_running": False,
        "zinda_running": False,
        "cp_loop_running": False,
        "bot_loop_running": False,
        "oneword_running": False,
        "user_stopped": False,
        "state_dict": {},
        "raid_session": {"chat_id": None, "target_sender_id": None, "lines": [], "current_index": 0, "latest_target_msg_id": None},
        "oneword_session": {"chat_id": None, "target_sender_id": None, "words": [], "current_index": 0, "latest_target_msg_id": None}
    }
    await event.respond("📱 Apna Telegram account ka **Phone Number** country code ke sath bhejein (Jaise: `+918696862902`)")

@bot.on(events.NewMessage(pattern=r"^/logout$"))
async def logout_cmd(event):
    if not event.is_private:
        return
    user_id = event.sender_id
    if user_id in active_users:
        try:
            await active_users[user_id]["client"].disconnect()
        except Exception:
            pass
        del active_users[user_id]
        await event.respond("🔓 Aapka userbot successfully logout kar diya gaya hai.")
    else:
        await event.respond("❌ Aapka koi userbot logged in nahi hai.")

@bot.on(events.NewMessage(incoming=True))
async def bot_private_handler(event):
    if not event.is_private:
        return
    user_id = event.sender_id
    if user_id not in active_users:
        return

    u_data = active_users[user_id]
    state = u_data.get("state")
    if not state:
        return

    text = event.raw_text.strip()
    if text.startswith("/"):
        return

    if state == "waiting_phone":
        if not text.startswith("+"):
            text = "+" + text
        u_data["phone_number"] = text
        u_data["state"] = "processing_phone"
        try:
            await event.respond("🔄 OTP bheja ja raha hai aapke Telegram account par, please wait...")
            temp_client = TelegramClient(f"session_{user_id}", api_id, api_hash)
            await temp_client.connect()
            sent_code = await temp_client.send_code_request(text)

            u_data["temp_client"] = temp_client
            u_data["phone_code_hash"] = sent_code.phone_code_hash
            u_data["state"] = "waiting_otp"

            await event.respond(
                "✅ OTP bhej diya gaya hai!\n"
                "Ab apna OTP **space dekar** bhejein (Jaise: `1 2 3 4 5`)."
            )
        except Exception as e:
            await event.respond(f"❌ Error: {e}\nDobara sahi number bhejein (jaise `+91...`).")
            u_data["state"] = "waiting_phone"

    elif state == "waiting_otp":
        otp_code = re.sub(r"\s+", "", text)
        temp_client = u_data["temp_client"]
        phone = u_data["phone_number"]
        phone_code_hash = u_data["phone_code_hash"]

        try:
            await temp_client.sign_in(phone=phone, code=otp_code, phone_code_hash=phone_code_hash)
            u_data["client"] = temp_client
            u_data["state"] = None
            setup_userbot_handlers(temp_client, user_id)
            await event.respond("✅ Userbot successfully logged in & connected!\nAb aap apne Saved Messages me `.auto` use kar sakte hain.")
        except SessionPasswordNeededError:
            u_data["state"] = "waiting_password"
            await event.respond("🔒 Aapke account par 2-Step Verification (Password) laga hai. Apna Cloud Password bhejein:")
        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            await event.respond("❌ Galat ya Expired OTP! Kripya `/add` se dobara shuru karein.")
            try:
                await temp_client.disconnect()
            except Exception:
                pass
            u_data["state"] = None
        except Exception as e:
            await event.respond(f"❌ Login Failed Error: {e}\nDobara `/add` try karein.")
            u_data["state"] = None

    elif state == "waiting_password":
        temp_client = u_data["temp_client"]
        try:
            await temp_client.sign_in(password=text)
            u_data["client"] = temp_client
            u_data["state"] = None
            setup_userbot_handlers(temp_client, user_id)
            await event.respond("✅ 2-Step Password verified! Userbot successfully logged in.\nAb aap `.auto` use kar sakte hain.")
        except Exception as e:
            await event.respond(f"❌ Galat Password! Error: {e}\nDobara `/add` se try karein.")
            try:
                await temp_client.disconnect()
            except Exception:
                pass
            u_data["state"] = None

def setup_userbot_handlers(user_client, owner_id):
    u_data = active_users[owner_id]

    @user_client.on(events.NewMessage(incoming=True))
    async def live_target_tracker(event):
        if not event.is_group:
            return
        if event.chat_id == u_data["raid_session"].get("chat_id") and event.sender_id == u_data["raid_session"].get("target_sender_id"):
            if is_valid_text_message(event):
                u_data["raid_session"]["latest_target_msg_id"] = event.id

        if event.chat_id == u_data["oneword_session"].get("chat_id") and event.sender_id == u_data["oneword_session"].get("target_sender_id"):
            if is_valid_text_message(event):
                u_data["oneword_session"]["latest_target_msg_id"] = event.id

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.ultra$"))
    async def set_ultra_mode(event):
        if event.chat_id != event.sender_id:
            return
        u_data["current_speed_mode"] = "ultra"
        await event.reply("⚡ Mode Set: ULTRA\n• Speed: Max Speed")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.hard$"))
    async def set_hard_mode(event):
        if event.chat_id != event.sender_id:
            return
        u_data["current_speed_mode"] = "hard"
        await event.reply("⚡ Mode Set: HARD\n• Balanced Speed Set")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.medium$"))
    async def set_medium_mode(event):
        if event.chat_id != event.sender_id:
            return
        u_data["current_speed_mode"] = "medium"
        await event.reply("⚡ Mode Set: MEDIUM\n• Moderate Speed Set")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.speed\s+(.+)"))
    async def set_custom_speed(event):
        if event.chat_id != event.sender_id:
            return
        try:
            val = float(event.pattern_match.group(1).strip())
            if val < 0.03:
                val = 0.03
            u_data["custom_delay_seconds"] = val
            u_data["current_speed_mode"] = "custom"
            await event.reply(f"⚡ Custom Speed Set Successfully!\n• Delay: {val} seconds per message.")
        except ValueError:
            await event.reply("❌ Invalid format! Sahi tarika: `.speed 0.5` ya `.speed 2`")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.setcp$"))
    async def set_cp_handler(event):
        if event.chat_id != event.sender_id:
            return
        if not event.is_reply:
            await event.reply("Paragraph text par reply karke `.setcp` bhejein.")
            return
        replied_msg = await event.get_reply_message()
        if not replied_msg or not replied_msg.raw_text:
            await event.reply("Koi text nahi mila!")
            return
        lines = [line.strip() for line in replied_msg.raw_text.splitlines() if line.strip()]
        if lines:
            u_data["cp_responses"] = lines
            u_data["cp_index"] = 0
            await event.reply(f"✅ Target CP Paragraph Loaded! ({len(lines)} lines)")
        else:
            await event.reply("Paragraph empty hai.")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.setbot$"))
    async def set_bot_handler(event):
        if event.chat_id != event.sender_id:
            return
        if not event.is_reply:
            await event.reply("Paragraph text par reply karke `.setbot` bhejein.")
            return
        replied_msg = await event.get_reply_message()
        if not replied_msg or not replied_msg.raw_text:
            await event.reply("Koi text nahi mila!")
            return
        lines = [line.strip() for line in replied_msg.raw_text.splitlines() if line.strip()]
        if lines:
            u_data["bot_responses"] = lines
            u_data["bot_index"] = 0
            await event.reply(f"✅ Target BOT Paragraph Loaded! ({len(lines)} lines)")
        else:
            await event.reply("Paragraph empty hai.")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.setzinda$"))
    async def set_zinda_handler(event):
        if event.chat_id != event.sender_id:
            return
        if not event.is_reply:
            await event.reply("Paragraph text par reply karke `.setzinda` bhejein.")
            return
        replied_msg = await event.get_reply_message()
        if not replied_msg or not replied_msg.raw_text:
            await event.reply("Koi text nahi mila!")
            return
        lines = [line.strip() for line in replied_msg.raw_text.splitlines() if line.strip()]
        if lines:
            u_data["zinda_responses"] = lines
            u_data["zinda_index"] = 0
            await event.reply(f"✅ Zinda Paragraph Loaded! ({len(lines)} lines)")
        else:
            await event.reply("Paragraph empty hai.")

    async def run_raid():
        raid_session = u_data["raid_session"]
        chat_id = raid_session["chat_id"]
        target_sender_id = raid_session["target_sender_id"]
        lines = raid_session["lines"]

        while u_data["raid_running"] and not u_data["user_stopped"]:
            idx = raid_session["current_index"]
            if idx >= len(lines):
                break
            line = lines[idx]
            try:
                current_target_msg_id = None
                while u_data["raid_running"] and not u_data["user_stopped"]:
                    current_target_msg_id = await get_best_available_target_message(user_client, chat_id, target_sender_id, raid_session)
                    if current_target_msg_id:
                        break
                    await asyncio.sleep(0.5)

                if not u_data["raid_running"] or u_data["user_stopped"]:
                    break

                delay = get_delay(u_data, "main")
                if delay >= 1.0:
                    async with user_client.action(chat_id, "typing"):
                        await asyncio.sleep(delay - 0.5)
                    await asyncio.sleep(0.5)
                else:
                    await asyncio.sleep(delay)

                if not u_data["raid_running"] or u_data["user_stopped"]:
                    break

                await user_client.send_message(chat_id, line, reply_to=current_target_msg_id)
                raid_session["current_index"] += 1
            except Exception:
                await asyncio.sleep(0.5)

        u_data["raid_running"] = False
        if raid_session["current_index"] >= len(lines) and not u_data["user_stopped"]:
            await user_client.send_message(owner_id, "✅ Main Paragraph Raid Finished completely!")

    async def run_oneword_raid():
        oneword_session = u_data["oneword_session"]
        chat_id = oneword_session["chat_id"]
        target_sender_id = oneword_session["target_sender_id"]
        words = oneword_session["words"]

        while u_data["oneword_running"] and not u_data["user_stopped"]:
            idx = oneword_session["current_index"]
            if idx >= len(words):
                break
            word = words[idx]
            try:
                current_target_msg_id = None
                while u_data["oneword_running"] and not u_data["user_stopped"]:
                    current_target_msg_id = await get_best_available_target_message(user_client, chat_id, target_sender_id, oneword_session)
                    if current_target_msg_id:
                        break
                    await asyncio.sleep(0.3)

                if not u_data["oneword_running"] or u_data["user_stopped"]:
                    break

                delay = get_delay(u_data, "oneword")
                await asyncio.sleep(delay)

                if not u_data["oneword_running"] or u_data["user_stopped"]:
                    break

                await user_client.send_message(chat_id, word, reply_to=current_target_msg_id)
                oneword_session["current_index"] += 1
            except Exception:
                await asyncio.sleep(0.3)

        u_data["oneword_running"] = False
        if oneword_session["current_index"] >= len(words) and not u_data["user_stopped"]:
            await user_client.send_message(owner_id, "✅ One-Word Raid Finished completely!")

    async def run_custom_loop(loop_name):
        raid_session = u_data["raid_session"]
        chat_id = raid_session.get("chat_id")
        target_sender_id = raid_session.get("target_sender_id")

        def is_active():
            if u_data["user_stopped"]:
                return False
            if loop_name == "zinda":
                return u_data["zinda_running"]
            elif loop_name == "cp":
                return u_data["cp_loop_running"]
            elif loop_name == "bot":
                return u_data["bot_loop_running"]
            return False

        while is_active():
            try:
                current_target_msg_id = None
                while is_active():
                    current_target_msg_id = await get_best_available_target_message(user_client, chat_id, target_sender_id, raid_session)
                    if current_target_msg_id:
                        break
                    await asyncio.sleep(0.5)

                if not is_active():
                    break

                if loop_name == "cp":
                    line = u_data["cp_responses"][u_data["cp_index"] % len(u_data["cp_responses"])]
                elif loop_name == "bot":
                    line = u_data["bot_responses"][u_data["bot_index"] % len(u_data["bot_responses"])]
                elif loop_name == "zinda":
                    line = u_data["zinda_responses"][u_data["zinda_index"] % len(u_data["zinda_responses"])]

                delay = get_delay(u_data, loop_name)
                if delay >= 1.0:
                    async with user_client.action(chat_id, "typing"):
                        await asyncio.sleep(delay - 0.5)
                    await asyncio.sleep(0.5)
                else:
                    await asyncio.sleep(delay)

                if not is_active():
                    break

                await user_client.send_message(chat_id, line, reply_to=current_target_msg_id)

                if loop_name == "cp":
                    u_data["cp_index"] = (u_data["cp_index"] + 1) % len(u_data["cp_responses"])
                elif loop_name == "bot":
                    u_data["bot_index"] = (u_data["bot_index"] + 1) % len(u_data["bot_responses"])
                elif loop_name == "zinda":
                    u_data["zinda_index"] = (u_data["zinda_index"] + 1) % len(u_data["zinda_responses"])
            except Exception:
                await asyncio.sleep(0.5)

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.auto$"))
    async def start_auto(event):
        if event.chat_id != event.sender_id:
            return
        u_data["user_stopped"] = False
        u_data["state_dict"] = {"step": "link"}
        await event.reply("Send me target message link")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.oneword$"))
    async def start_oneword_cmd(event):
        if event.chat_id != event.sender_id:
            return
        u_data["user_stopped"] = False
        u_data["state_dict"] = {"step": "oneword_link"}
        await event.reply("Send me target message link for One-Word Raid:")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.target$"))
    async def change_target_cmd(event):
        if event.chat_id != event.sender_id:
            return
        u_data["raid_running"] = False
        u_data["zinda_running"] = False
        u_data["cp_loop_running"] = False
        u_data["bot_loop_running"] = False
        u_data["oneword_running"] = False
        u_data["user_stopped"] = False
        u_data["state_dict"] = {"step": "change_target"}
        await event.reply("🔄 Naye target ka message link bhejo:")

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.stop$"))
    async def stop_auto(event):
        if event.chat_id != event.sender_id:
            return
        u_data["raid_running"] = False
        u_data["zinda_running"] = False
        u_data["cp_loop_running"] = False
        u_data["bot_loop_running"] = False
        u_data["oneword_running"] = False
        u_data["user_stopped"] = True
        u_data["state_dict"] = {}

        await event.reply(
            f"🛑 Bot completely STOPPED & LOCKED!\n"
            f"• Main Index: {u_data['raid_session']['current_index']}/{len(u_data['raid_session']['lines'])}\n"
            f"• OneWord Index: {u_data['oneword_session']['current_index']}/{len(u_data['oneword_session']['words'])}\n\n"
            f"Unlock & Resume: `.start main`, `.onestart`, `.start cp`, etc."
        )

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.reboot$"))
    async def reboot_oneword(event):
        if event.chat_id != event.sender_id:
            return
        u_data["oneword_running"] = False
        await event.reply(
            f"🔄 One-Word Raid REBOOTED & STOPPED!\n"
            f"• Stopped at word index: {u_data['oneword_session']['current_index']}/{len(u_data['oneword_session']['words'])}\n"
            f"• Resume using: `.onestart`"
        )

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.(start main|start|resume)$"))
    async def resume_auto(event):
        if event.chat_id != event.sender_id:
            return
        u_data["zinda_running"] = False
        u_data["cp_loop_running"] = False
        u_data["bot_loop_running"] = False
        u_data["oneword_running"] = False
        u_data["user_stopped"] = False

        if u_data["raid_running"]:
            await event.reply("Main raid already chal rahi hai!")
            return

        if not u_data["raid_session"]["lines"] or u_data["raid_session"]["current_index"] >= len(u_data["raid_session"]["lines"]):
            await event.reply("Koi paused main raid nahi mili. Nayi raid ke liye `.auto` use karein.")
            return

        u_data["raid_running"] = True
        await event.reply(f"▶️ Main Raid Resumed from line {u_data['raid_session']['current_index'] + 1}...")
        asyncio.create_task(run_raid())

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.onestart$"))
    async def resume_oneword(event):
        if event.chat_id != event.sender_id:
            return
        u_data["raid_running"] = False
        u_data["zinda_running"] = False
        u_data["cp_loop_running"] = False
        u_data["bot_loop_running"] = False
        u_data["user_stopped"] = False

        if u_data["oneword_running"]:
            await event.reply("One-Word raid already chal rahi hai!")
            return

        if not u_data["oneword_session"]["words"] or u_data["oneword_session"]["current_index"] >= len(u_data["oneword_session"]["words"]):
            await event.reply("Koi paused One-Word raid nahi mili. Nayi raid ke liye `.oneword` use karein.")
            return

        u_data["oneword_running"] = True
        await event.reply(f"▶️ One-Word Raid Resumed from word index {u_data['oneword_session']['current_index'] + 1}...")
        asyncio.create_task(run_oneword_raid())

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.start cp$"))
    async def start_cp_cmd(event):
        if event.chat_id != event.sender_id:
            return
        if not u_data["cp_responses"]:
            await event.reply("Pehle `.setcp` karke CP paragraph load karein!")
            return
        if not u_data["raid_session"].get("chat_id"):
            await event.reply("Pehle kisi target ko lock karein!")
            return

        u_data["raid_running"] = False
        u_data["zinda_running"] = False
        u_data["bot_loop_running"] = False
        u_data["oneword_running"] = False
        u_data["cp_loop_running"] = True
        u_data["user_stopped"] = False

        await event.reply(f"⚡ CP Spam resumed from line {u_data['cp_index'] + 1}/{len(u_data['cp_responses'])}!")
        asyncio.create_task(run_custom_loop("cp"))

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.start bot$"))
    async def start_bot_cmd(event):
        if event.chat_id != event.sender_id:
            return
        if not u_data["bot_responses"]:
            await event.reply("Pehle `.setbot` karke BOT paragraph load karein!")
            return
        if not u_data["raid_session"].get("chat_id"):
            await event.reply("Pehle kisi target ko lock karein!")
            return

        u_data["raid_running"] = False
        u_data["zinda_running"] = False
        u_data["cp_loop_running"] = False
        u_data["oneword_running"] = False
        u_data["bot_loop_running"] = True
        u_data["user_stopped"] = False

        await event.reply(f"⚡ BOT Spam resumed from line {u_data['bot_index'] + 1}/{len(u_data['bot_responses'])}!")
        asyncio.create_task(run_custom_loop("bot"))

    @user_client.on(events.NewMessage(outgoing=True, pattern=r"^\.(start zinda|startzinda)$"))
    async def start_zinda_cmd(event):
        if event.chat_id != event.sender_id:
            return
        if not u_data["zinda_responses"]:
            await event.reply("Pehle `.setzinda` use karke paragraph load karein!")
            return
        if not u_data["raid_session"].get("chat_id"):
            await event.reply("Pehle kisi target ko lock karein!")
            return

        u_data["raid_running"] = False
        u_data["cp_loop_running"] = False
        u_data["bot_loop_running"] = False
        u_data["oneword_running"] = False
        u_data["zinda_running"] = True
        u_data["user_stopped"] = False

        await event.reply(f"⚡ Zinda Spam resumed from line {u_data['zinda_index'] + 1}/{len(u_data['zinda_responses'])}!")
        asyncio.create_task(run_custom_loop("zinda"))

    @user_client.on(events.NewMessage(outgoing=True))
    async def setup_pipeline_handler(event):
        if event.chat_id != event.sender_id:
            return
        st = u_data.get("state_dict", {})
        step = st.get("step")
        if not step:
            return

        if step == "change_target" and event.is_reply:
            link = event.raw_text.strip()
            match = re.search(r"t\.me\/(.+)\/(\d+)", link)
            if not match:
                return
            chat_part = match.group(1)
            target_msg_id = int(match.group(2))
            try:
                if chat_part.startswith("c/"):
                    chat_id = int("-100" + chat_part.split("/")[1])
                else:
                    entity = await user_client.get_entity(chat_part)
                    chat_id = entity.id

                target_msg = await user_client.get_messages(chat_id, ids=target_msg_id)
                if not target_msg:
                    await event.reply("Target message exist nahi karta!")
                    u_data["state_dict"] = {}
                    return

                target_sender_id = target_msg.sender_id

                u_data["raid_running"] = False
                u_data["zinda_running"] = False
                u_data["cp_loop_running"] = False
                u_data["bot_loop_running"] = False
                u_data["oneword_running"] = False
                u_data["user_stopped"] = False

                await asyncio.sleep(0.3)

                u_data["raid_session"]["chat_id"] = chat_id
                u_data["raid_session"]["target_sender_id"] = target_sender_id
                u_data["raid_session"]["latest_target_msg_id"] = target_msg_id

                u_data["oneword_session"]["chat_id"] = chat_id
                u_data["oneword_session"]["target_sender_id"] = target_sender_id
                u_data["oneword_session"]["latest_target_msg_id"] = target_msg_id

                u_data["state_dict"] = {}
                await event.reply(f"🎯 Target Changed! (ID: {target_sender_id})")
            except Exception:
                u_data["state_dict"] = {}

        elif step == "link" and event.is_reply:
            link = event.raw_text.strip()
            match = re.search(r"t\.me\/(.+)\/(\d+)", link)
            if not match:
                return
            chat_part = match.group(1)
            target_msg_id = int(match.group(2))
            try:
                if chat_part.startswith("c/"):
                    chat_id = int("-100" + chat_part.split("/")[1])
                else:
                    entity = await user_client.get_entity(chat_part)
                    chat_id = entity.id

                target_msg = await user_client.get_messages(chat_id, ids=target_msg_id)
                if not target_msg:
                    await event.reply("Target message exist nahi karta!")
                    u_data["state_dict"] = {}
                    return

                target_sender_id = target_msg.sender_id

                st["chat_id"] = chat_id
                st["target_sender_id"] = target_sender_id
                st["step"] = "message"

                u_data["raid_session"]["chat_id"] = chat_id
                u_data["raid_session"]["target_sender_id"] = target_sender_id
                u_data["raid_session"]["latest_target_msg_id"] = target_msg_id

                await event.reply(f"Target locked (ID: {target_sender_id})!\nAb paragraph bhejein.")
            except Exception:
                u_data["state_dict"] = {}

        elif step == "message" and event.is_reply:
            text = event.raw_text.strip()
            items = [line.strip() for line in text.splitlines() if line.strip()]

            u_data["raid_session"]["lines"] = items
            u_data["raid_session"]["current_index"] = 0

            u_data["state_dict"] = {}
            u_data["zinda_running"] = False
            u_data["cp_loop_running"] = False
            u_data["bot_loop_running"] = False
            u_data["oneword_running"] = False
            u_data["user_stopped"] = False
            u_data["raid_running"] = True

            await event.reply(f"🚀 Paragraph Raid Started ({len(items)} lines)")
            asyncio.create_task(run_raid())

        elif step == "oneword_link" and event.is_reply:
            link = event.raw_text.strip()
            match = re.search(r"t\.me\/(.+)\/(\d+)", link)
            if not match:
                return
            chat_part = match.group(1)
            target_msg_id = int(match.group(2))
            try:
                if chat_part.startswith("c/"):
                    chat_id = int("-100" + chat_part.split("/")[1])
                else:
                    entity = await user_client.get_entity(chat_part)
                    chat_id = entity.id

                target_msg = await user_client.get_messages(chat_id, ids=target_msg_id)
                if not target_msg:
                    await event.reply("Target message exist nahi karta!")
                    u_data["state_dict"] = {}
                    return

                target_sender_id = target_msg.sender_id

                st["chat_id"] = chat_id
                st["target_sender_id"] = target_sender_id
                st["step"] = "oneword_message"

                u_data["oneword_session"]["chat_id"] = chat_id
                u_data["oneword_session"]["target_sender_id"] = target_sender_id
                u_data["oneword_session"]["latest_target_msg_id"] = target_msg_id

                await event.reply(f"Target locked for One-Word (ID: {target_sender_id})!\nAb message bhejein.")
            except Exception:
                u_data["state_dict"] = {}

        elif step == "oneword_message" and event.is_reply:
            text = event.raw_text.strip()
            words = text.split()

            u_data["oneword_session"]["words"] = words
            u_data["oneword_session"]["current_index"] = 0

            u_data["state_dict"] = {}
            u_data["raid_running"] = False
            u_data["zinda_running"] = False
            u_data["cp_loop_running"] = False
            u_data["bot_loop_running"] = False
            u_data["user_stopped"] = False
            u_data["oneword_running"] = True

            await event.reply(f"🚀 One-Word Raid Started ({len(words)} words)")
            asyncio.create_task(run_oneword_raid())

# --- Web Server for Render Port Binding ---
async def handle(request):
    return web.Response(text="Bot is running successfully!")

async def start_web_server():
    app = web.Application()
    app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    await start_web_server()
    print("Web Server Started Successfully...")
    await bot.start(bot_token=BOT_TOKEN)
    print("Telegram Bot Started Successfully...")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
