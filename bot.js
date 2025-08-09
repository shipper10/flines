const TelegramBot = require("node-telegram-bot-api");
const fs = require("fs-extra");
const { HoyolabClient, Games } = require("node-hoyolab");

const TOKEN = process.env.BOT_TOKEN;
if (!TOKEN) {
  console.error("Error: BOT_TOKEN environment variable not set.");
  process.exit(1);
}
const bot = new TelegramBot(TOKEN, { polling: true });

const DATA_FILE = "data.json";
let users = {};
if (fs.existsSync(DATA_FILE)) {
  try { users = fs.readJSONSync(DATA_FILE); } catch(e){ users = {}; }
}

function saveData() {
  try {
    fs.writeJSONSync(DATA_FILE, users, { spaces: 2 });
  } catch (e) {
    console.error("Failed to save data.json", e);
  }
}

// /setcookies <ltoken_v2> <ltuid_v2>
bot.onText(/\/setcookies\s+(.+)\s+(.+)/, (msg, match) => {
  const chatId = msg.from.id;
  const ltoken = match[1].trim();
  const ltuid = match[2].trim();
  users[chatId] = { ltoken_v2: ltoken, ltuid_v2: ltuid };
  saveData();
  bot.sendMessage(msg.chat.id, "✅ تم حفظ الكوكيز في التخزين (خاص بحسابك).");
});

// /removecookies
bot.onText(/\/removecookies/, (msg) => {
  const chatId = msg.from.id;
  if (users[chatId]) {
    delete users[chatId];
    saveData();
    return bot.sendMessage(msg.chat.id, "✅ تم حذف الكوكيز.");
  }
  bot.sendMessage(msg.chat.id, "⚠️ لا توجد كوكيز محفوظة لحسابك.");
});

// /chronicles
bot.onText(/\/chronicles/, async (msg) => {
  const chatId = msg.from.id;
  const cookies = users[chatId];
  if (!cookies) return bot.sendMessage(msg.chat.id, "❌ لم تُسجل كوكيزك. استخدم /setcookies <ltoken_v2> <ltuid_v2>");
  const hoyo = new HoyolabClient({ cookie: cookies });
  try {
    const res = await hoyo.getBattleChronicles(Games.GENSHIN_IMPACT);
    if (!res || !res.list || res.list.length === 0) return bot.sendMessage(msg.chat.id, "ℹ️ لا توجد سجلات.");
    const lines = res.list.slice(0,8).map((c,i)=>`${i+1}. ${c.name||c.title||'Unknown'} ${c.level||''}`.trim());
    bot.sendMessage(msg.chat.id, `🎯 Battle Chronicles:\n${lines.join('\n')}`);
  } catch (e) {
    console.error("chronicles err", e);
    bot.sendMessage(msg.chat.id, "⚠️ حدث خطأ أثناء جلب Battle Chronicles. تحقق من الكوكيز.");
  }
});

// /dailynote
bot.onText(/\/dailynote/, async (msg) => {
  const chatId = msg.from.id;
  const cookies = users[chatId];
  if (!cookies) return bot.sendMessage(msg.chat.id, "❌ لم تُسجل كوكيزك. استخدم /setcookies <ltoken_v2> <ltuid_v2>");
  const hoyo = new HoyolabClient({ cookie: cookies });
  try {
    const note = await hoyo.getDailyNote(Games.GENSHIN_IMPACT);
    if (!note) return bot.sendMessage(msg.chat.id, "ℹ️ لا توجد بيانات Daily Note.");
    const out = [];
    if (note.current_resin !== undefined) out.push(`🔋 Resin: ${note.current_resin}/${note.max_resin||'??'}`);
    if (note.realm_currency !== undefined) out.push(`🏰 Realm Currency: ${note.realm_currency}`);
    bot.sendMessage(msg.chat.id, out.join('\n') || 'ℹ️ لا توجد معلومات.');
  } catch (e) {
    console.error("dailynote err", e);
    bot.sendMessage(msg.chat.id, "⚠️ خطأ أثناء جلب Daily Note.");
  }
});

bot.onText(/\/me/, (msg) => {
  const chatId = msg.from.id;
  const cookies = users[chatId];
  if (!cookies) return bot.sendMessage(msg.chat.id, "❌ لم تُسجل الكوكيز بعد.");
  bot.sendMessage(msg.chat.id, `✅ لديك كوكيز محفوظة (ltuid_v2: ${cookies.ltuid_v2}).`);
});

bot.onText(/\/start/, (msg) => {
  bot.sendMessage(msg.chat.id, "مرحباً! استخدم /help لرؤية الأوامر.\n/setcookies <ltoken_v2> <ltuid_v2>");
});

bot.onText(/\/help/, (msg) => {
  bot.sendMessage(msg.chat.id, "الأوامر:\n/setcookies <ltoken_v2> <ltuid_v2>\n/removecookies\n/chronicles\n/dailynote\n/me");
});
