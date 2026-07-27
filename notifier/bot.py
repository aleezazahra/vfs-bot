import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from config import Config
from scrapers import VFSScraper, TLSScraper, BLSScraper

logger = logging.getLogger(__name__)

class SlotNotifierBot:
    def __init__(self):
        self.application = None
        self.scrapers = []
        self.chat_id = Config.CHAT_ID
        self.check_interval = Config.CHECK_INTERVAL
        self._init_scrapers()

    def _init_scrapers(self):
        """Instantiate scraper objects with config."""
        if Config.VFS_URL:
            self.scrapers.append(VFSScraper(
                username=Config.VFS_USERNAME,
                password=Config.VFS_PASSWORD,
                url=Config.VFS_URL,
                headless=Config.HEADLESS
            ))
        if Config.TLS_URL:
            self.scrapers.append(TLSScraper(
                username=Config.TLS_USERNAME,
                password=Config.TLS_PASSWORD,
                url=Config.TLS_URL,
                headless=Config.HEADLESS
            ))
        if Config.BLS_URL:
            self.scrapers.append(BLSScraper(
                username=Config.BLS_USERNAME,
                password=Config.BLS_PASSWORD,
                url=Config.BLS_URL,
                headless=Config.HEADLESS
            ))
        if not self.scrapers:
            logger.warning("No scraper URLs configured. Please set at least one URL in .env")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Store chat ID and send a welcome message."""
        self.chat_id = update.effective_chat.id
        logger.info(f"Chat ID registered: {self.chat_id}")
        await update.message.reply_text(
            "Bot started! I will notify you when visa appointment slots open.\n"
            "Use /check to manually check now."
        )

    async def manual_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manually trigger a slot check and send results."""
        if not self.scrapers:
            await update.message.reply_text("No scrapers configured. Please set URLs in .env")
            return
        await update.message.reply_text("Checking slots... please wait.")
        results = []
        for scraper in self.scrapers:
            available, msg = scraper.run_check()
            results.append(msg)
            # Also update internal last_status to avoid duplicate alerts later
            if available:
                scraper.last_status = True
            else:
                scraper.last_status = False
        await update.message.reply_text("\n".join(results))

    async def periodic_check(self):
        """Periodic check loop, sends alerts to stored chat_id."""
        while True:
            await asyncio.sleep(self.check_interval)
            if not self.chat_id:
                logger.warning("No chat_id set; waiting for /start command.")
                continue
            for scraper in self.scrapers:
                available, msg = scraper.run_check()
                if scraper.should_alert(available):
                    # Send alert
                    await self.application.bot.send_message(
                        chat_id=self.chat_id,
                        text=f"🚨 ALERT: {msg}"
                    )
                    logger.info(f"Alert sent for {scraper.__class__.__name__}")
                else:
                    logger.debug(msg)

    def run(self):
        """Start the bot and periodic checker."""
        if not Config.TELEGRAM_TOKEN:
            raise ValueError("TELEGRAM_TOKEN not set in environment.")

        self.application = Application.builder().token(Config.TELEGRAM_TOKEN).build()
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("check", self.manual_check))

        # Start the background task for periodic checks
        loop = asyncio.get_event_loop()
        loop.create_task(self.periodic_check())

        logger.info("Bot is running...")
        self.application.run_polling()

def run_bot():
    bot = SlotNotifierBot()
    bot.run()