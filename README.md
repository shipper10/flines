# flines - Telegram HoYoLab Bot

Quick start:

1. Set BOT_TOKEN environment variable (in Koyeb use Environment Variables).
2. Install locally: `npm install`
3. Run: `BOT_TOKEN=xxx npm start`

Deploy on Koyeb:
- Push repository to GitHub.
- In Koyeb create new app and connect the repo.
- Set Environment variable BOT_TOKEN with your bot token.
- Deploy (Koyeb will run `npm ci` using package-lock.json).
