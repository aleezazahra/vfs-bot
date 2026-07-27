import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))
    CHAT_ID = os.getenv("CHAT_ID")  # can be None initially
    CAPTCHA_API_KEY = os.getenv("CAPTCHA_API_KEY")

    # VFS
    VFS_USERNAME = os.getenv("VFS_USERNAME")
    VFS_PASSWORD = os.getenv("VFS_PASSWORD")
    VFS_URL = os.getenv("VFS_URL")

    # TLS
    TLS_USERNAME = os.getenv("TLS_USERNAME")
    TLS_PASSWORD = os.getenv("TLS_PASSWORD")
    TLS_URL = os.getenv("TLS_URL")

    # BLS
    BLS_USERNAME = os.getenv("BLS_USERNAME")
    BLS_PASSWORD = os.getenv("BLS_PASSWORD")
    BLS_URL = os.getenv("BLS_URL")

    # Optional: headless mode (default False for debugging)
    HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"