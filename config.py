import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Optional 2Captcha API key used to solve the VFS image CAPTCHA.
    CAPTCHA_API_KEY = os.getenv("CAPTCHA_API_KEY")

    # Directory where scraped login sessions (cookies) are persisted so the
    # app can stay logged in across runs and skip OTP on subsequent checks.
    PROFILE_DIR = os.getenv("PROFILE_DIR", "profiles")

    # Defaults for CLI testing via text_check.py (the GUI stores per-user
    # settings in gui_config.json instead).
    VFS_USERNAME = os.getenv("VFS_USERNAME")
    VFS_PASSWORD = os.getenv("VFS_PASSWORD")
    VFS_URL = os.getenv("VFS_URL")
    VFS_APPOINTMENT_URL = os.getenv("VFS_APPOINTMENT_URL")

    # Optional: headless mode for CLI tests (default False for debugging)
    HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
