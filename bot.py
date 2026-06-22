

TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "مرحباً! أنا بوتك 🤖")

@bot.message_handler(func=lambda m: True)
def echo(message):
    bot.reply_to(message, message.text)

bot.infinity_polling()
