# bot.py
import os
import json
import asyncio
import traceback
from typing import Optional, Any, Dict, List

import httpx
import genshin
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("Please set BOT_TOKEN environment variable")

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
DATA_FILE = "users.json"
POLL_TIMEOUT = 30  # seconds for long polling

# ensure users file exists
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False, indent=2)

_users_lock = asyncio.Lock()


def load_users_sync() -> Dict[str, Dict[str, str]]:
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


async def save_users(users: Dict[str, Dict[str, str]]):
    async with _users_lock:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)


async def send_message(client: httpx.AsyncClient, chat_id: int, text: str, parse_mode: str = "Markdown"):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    try:
        await client.post(f"{API_URL}/sendMessage", json=payload, timeout=20.0)
    except Exception as e:
        print("send_message error:", e)


async def create_genshin_client(creds: Dict[str, str], uid: Optional[str] = None):
    """
    Tries to create a genshin.Client using possible cookie shapes.
    creds may contain: ltuid & ltoken OR cookie_token.
    Returns a genshin.Client instance or raises.
    """
    cookies = None
    if "ltuid" in creds and "ltoken" in creds:
        cookies = {"ltuid": creds["ltuid"], "ltoken": creds["ltoken"]}
    elif "cookie_token" in creds:
        cookies = {"cookie_token": creds["cookie_token"]}
    else:
        raise ValueError("No credentials found")

    try:
        if uid:
            return genshin.Client(cookies, uid=int(uid))
        return genshin.Client(cookies)
    except TypeError:
        # fallback if genshin.Client signature differs
        return genshin.Client(cookies)
    except Exception:
        # re-raise other errors to be handled by caller
        raise


async def try_functions(client_obj: Any, names: List[str], *args, **kwargs):
    """
    Attempt calling several coroutine attribute names on client_obj.
    Returns the first successful result, or raises the last exception.
    """
    last_exc = None
    for name in names:
        func = getattr(client_obj, name, None)
        if callable(func):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exc = e
                continue
    if last_exc:
        raise last_exc
    raise RuntimeError(f"No callable found among: {names}")


# ---------- Command handlers (simple text-based commands) ----------
async def handle_start(chat_id: int, client_http: httpx.AsyncClient):
    text = (
        "👋 أهلاً! بوت Genshin (بدون python-telegram-bot).\n\n"
        "الأوامر المدعومة:\n"
        "/link <ltuid> <ltoken> — ربط الحساب (أو `/link <cookie_token>`)\n"
        "/setuid <game_uid> — حفظ UID\n"
        "/resin — عرض Resin\n"
        "/abyss — عرض Spiral Abyss\n"
        "/stygian — عرض Stygian Onslaught\n"
        "/lobby — عرض Theater Lobby\n"
    )
    await send_message(client_http, chat_id, text)


async def handle_link(chat_id: int, args: List[str], client_http: httpx.AsyncClient):
    if len(args) == 2:
        ltuid, ltoken = args
        users = load_users_sync()
        users[str(chat_id)] = users.get(str(chat_id), {})
        users[str(chat_id)]["ltuid"] = ltuid
        users[str(chat_id)]["ltoken"] = ltoken
        await save_users(users)
        await send_message(client_http, chat_id, "✅ تم حفظ ltuid و ltoken بنجاح.")
        return
    elif len(args) == 1:
        cookie = args[0]
        users = load_users_sync()
        users[str(chat_id)] = users.get(str(chat_id), {})
        users[str(chat_id)]["cookie_token"] = cookie
        await save_users(users)
        await send_message(client_http, chat_id, "✅ تم حفظ cookie_token بنجاح.")
        return
    else:
        await send_message(client_http, chat_id, "❌ الصيغة: `/link ltuid ltoken` أو `/link cookie_token`")


async def handle_setuid(chat_id: int, args: List[str], client_http: httpx.AsyncClient):
    if len(args) != 1:
        await send_message(client_http, chat_id, "❌ الصيغة: `/setuid <game_uid>`")
        return
    uid = args[0]
    users = load_users_sync()
    users[str(chat_id)] = users.get(str(chat_id), {})
    users[str(chat_id)]["uid"] = uid
    await save_users(users)
    await send_message(client_http, chat_id, f"✅ تم حفظ UID: {uid}")


async def handle_resin(chat_id: int, client_http: httpx.AsyncClient):
    users = load_users_sync()
    u = users.get(str(chat_id))
    if not u:
        await send_message(client_http, chat_id, "⚠️ لم تقم بربط حسابك بعد. استخدم /link")
        return
    if "uid" not in u:
        await send_message(client_http, chat_id, "⚠️ لم تخزن UID بعد. استخدم /setuid <uid>")
        return
    try:
        client = await create_genshin_client(u, uid=u.get("uid"))
    except Exception as e:
        await send_message(client_http, chat_id, f"❌ خطأ بإنشاء عميل genshin: {e}")
        return

    # Try multiple possible function names to get notes/resin
    try:
        # often: get_notes(uid=...), get_genshin_notes(uid=...)
        notes = None
        try:
            notes = await try_functions(client, ["get_notes", "get_genshin_notes", "get_genshin_user"], uid=u.get("uid"))
        except TypeError:
            # fallback to call without uid
            notes = await try_functions(client, ["get_notes", "get_genshin_notes", "get_genshin_user"])
        # Extract resin from returned object/dict
        resin = None
        if hasattr(notes, "current_resin"):
            resin = f"{getattr(notes, 'current_resin')}/{getattr(notes, 'max_resin', '?')}"
        else:
            # dict-like
            try:
                resin = f"{notes.get('current_resin')}/{notes.get('max_resin')}"
            except Exception:
                resin = str(notes)
        await send_message(client_http, chat_id, f"🔋 Resin: {resin}")
    except Exception as e:
        await send_message(client_http, chat_id, f"❌ لم أتمكن من جلب Resin: {e}")


async def handle_abyss(chat_id: int, client_http: httpx.AsyncClient):
    users = load_users_sync()
    u = users.get(str(chat_id))
    if not u or "uid" not in u:
        await send_message(client_http, chat_id, "⚠️ تأكد من ربط الحساب و حفظ UID (/link و /setuid).")
        return
    try:
        client = await create_genshin_client(u, uid=u.get("uid"))
    except Exception as e:
        await send_message(client_http, chat_id, f"❌ خطأ بإنشاء عميل genshin: {e}")
        return

    candidates = ["get_spiral_abyss", "get_abyss", "spiral_abyss", "get_spiral", "get_abyss_info"]
    try:
        abyss = None
        try:
            abyss = await try_functions(client, candidates, u.get("uid"))
        except Exception:
            abyss = await try_functions(client, candidates)
        # Try to extract some fields
        total_stars = getattr(abyss, "total_stars", None) or (abyss.get("total_stars") if isinstance(abyss, dict) else None)
        floors = getattr(abyss, "floors", None) or (abyss.get("floors") if isinstance(abyss, dict) else None)
        lines = []
        if total_stars is not None:
            lines.append(f"⭐ إجمالي النجوم: {total_stars}")
        if floors:
            try:
                for f in floors:
                    idx = getattr(f, "index", None) or (f.get("index") if isinstance(f, dict) else None)
                    stars = getattr(f, "stars", None) or (f.get("stars") if isinstance(f, dict) else None)
                    lines.append(f"🔸 Floor {idx}: {stars}⭐")
            except Exception:
                lines.append(f"Floors: {len(floors)}")
        if not lines:
            lines = [str(abyss)]
        await send_message(client_http, chat_id, "\n".join(lines))
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        await send_message(client_http, chat_id, f"❌ خطأ جلب Abyss: {e}")


async def handle_stygian(chat_id: int, client_http: httpx.AsyncClient):
    users = load_users_sync()
    u = users.get(str(chat_id))
    if not u or "uid" not in u:
        await send_message(client_http, chat_id, "⚠️ تأكد من ربط الحساب و حفظ UID (/link و /setuid).")
        return
    try:
        client = await create_genshin_client(u, uid=u.get("uid"))
    except Exception as e:
        await send_message(client_http, chat_id, f"❌ خطأ بإنشاء عميل genshin: {e}")
        return

    candidates = ["get_stygian_onslaught", "stygian_onslaught", "get_stygian", "stygian"]
    try:
        data = None
        try:
            data = await try_functions(client, candidates, u.get("uid"))
        except Exception:
            data = await try_functions(client, candidates)
        await send_message(client_http, chat_id, f"⚔️ Stygian Onslaught:\n{data}")
    except Exception as e:
        await send_message(client_http, chat_id, f"❌ خطأ جلب Stygian: {e}")


async def handle_lobby(chat_id: int, client_http: httpx.AsyncClient):
    users = load_users_sync()
    u = users.get(str(chat_id))
    if not u or "uid" not in u:
        await send_message(client_http, chat_id, "⚠️ تأكد من ربط الحساب و حفظ UID (/link و /setuid).")
        return
    try:
        client = await create_genshin_client(u, uid=u.get("uid"))
    except Exception as e:
        await send_message(client_http, chat_id, f"❌ خطأ بإنشاء عميل genshin: {e}")
        return

    candidates = ["get_theater_lobby", "theater_lobby", "get_lobby", "lobby", "get_theater", "get_home", "home"]
    try:
        data = None
        try:
            data = await try_functions(client, candidates, u.get("uid"))
        except Exception:
            data = await try_functions(client, candidates)
        await send_message(client_http, chat_id, f"🎭 Theater Lobby:\n{data}")
    except Exception as e:
        await send_message(client_http, chat_id, f"❌ خطأ جلب Lobby: {e}")


# ---------- Update polling ----------
async def handle_update(update: Dict[str, Any], client_http: httpx.AsyncClient):
    message = update.get("message") or update.get("edited_message") or {}
    if not message:
        return
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text", "") or ""
    if not text:
        return

    # simple command parse
    parts = text.strip().split()
    cmd = parts[0].split("@")[0]  # remove bot username if provided
    args = parts[1:]

    try:
        if cmd == "/start":
            await handle_start(chat_id, client_http)
        elif cmd == "/link":
            await handle_link(chat_id, args, client_http)
        elif cmd == "/setuid":
            await handle_setuid(chat_id, args, client_http)
        elif cmd == "/resin":
            await handle_resin(chat_id, client_http)
        elif cmd == "/abyss":
            await handle_abyss(chat_id, client_http)
        elif cmd == "/stygian":
            await handle_stygian(chat_id, client_http)
        elif cmd == "/lobby":
            await handle_lobby(chat_id, client_http)
        else:
            # ignore other messages
            pass
    except Exception as e:
        tb = traceback.format_exc()
        print("handler error:", tb)
        await send_message(client_http, chat_id, f"❌ خطأ داخلي: {e}")


async def poll_updates():
    offset = None
    async with httpx.AsyncClient(timeout=POLL_TIMEOUT + 10) as client_http:
        while True:
            try:
                params = {"timeout": POLL_TIMEOUT}
                if offset:
                    params["offset"] = offset
                resp = await client_http.get(f"{API_URL}/getUpdates", params=params)
                j = resp.json()
                if not j.get("ok"):
                    print("getUpdates failed:", j)
                    await asyncio.sleep(2)
                    continue
                results = j.get("result", []) or []
                for upd in results:
                    offset = upd["update_id"] + 1
                    # handle each update concurrently but not blocking the poll loop
                    asyncio.create_task(handle_update(upd, client_http))
            except Exception as e:
                print("polling error:", e)
                await asyncio.sleep(3)


def main():
    print("Starting long-polling Telegram bot...")
    asyncio.run(poll_updates())


if __name__ == "__main__":
    main()
