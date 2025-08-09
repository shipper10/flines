Enka Telegram Bot - README
--------------------------
Files included:
- main.py             : Bot code
- accounts.json       : Stored UIDs for users (created automatically)
- requirements.txt    : Python dependencies
- images/             : directory for optional images (not required)
- README.txt          : this file

Quick start (local):
1. Create a Python v3.9+ virtualenv and activate it.
2. Install dependencies: pip install -r requirements.txt
3. Create a .env file containing BOT_TOKEN=your_bot_token or set BOT_TOKEN env var.
4. Run: python main.py
5. Use /set gen <UID> to save a Genshin UID, then /gen to list characters.

Deploy on Koyeb:
- Upload the project or push to a Git repository, create new app on Koyeb.
- Set build command to `pip install -r requirements.txt` (Koyeb auto-detects python buildpack).
- Set start command to `python main.py`
- Add environment variable BOT_TOKEN with your Telegram bot token.
- Deploy and check logs if any errors.

Notes:
- Enka.Network is a third-party service. If it times out or returns no characters,
  the bot will ask the user to verify the in-game Showcase and privacy settings.
- This project uses blocking HTTP calls but runs them in a thread via asyncio.to_thread
  to avoid blocking the bot event loop.
