import time
import logging
from abc import ABC, abstractmethod
from seleniumbase import Driver

logger = logging.getLogger(__name__)

class BaseScraper(ABC):
    def __init__(self, username=None, password=None, url=None, headless=False):
        self.username = username
        self.password = password
        self.url = url
        self.headless = headless
        self.driver = None
        self.last_status = None

    def _init_driver(self):
        self.driver = Driver(uc=True, headless=self.headless)
        self.driver.maximize_window()

    def _bypass_cloudflare(self):
        if not self.url:
            raise ValueError("No URL provided.")
        logger.info(f"Navigating to {self.url}")
        self.driver.uc_open_with_reconnect(self.url, reconnect_time=4)
        time.sleep(5)

        # Try CAPTCHA a few times
        for _ in range(3):
            try:
                self.driver.uc_gui_click_captcha()
                logger.info("CAPTCHA clicked.")
                break
            except:
                time.sleep(2)
        time.sleep(3)

        # If still challenge, extra try
        if "cloudflare" in self.driver.title.lower():
            time.sleep(5)
            try:
                self.driver.uc_gui_click_captcha()
            except:
                pass
            time.sleep(3)

    def login(self):
        pass

    @abstractmethod
    def check_slots(self):
        pass

    def run_check(self):
        try:
            self._init_driver()
            self._bypass_cloudflare()
            self.login()
            available = self.check_slots()
            msg = "✅ Slots AVAILABLE!" if available else "❌ No slots."
            return available, msg
        except Exception as e:
            logger.error(f"Error: {e}")
            return False, f"Error: {str(e)}"
        finally:
            if self.driver:
                self.driver.quit()

    def should_alert(self, available):
        if available and not self.last_status:
            self.last_status = True
            return True
        if not available:
            self.last_status = False
        return False