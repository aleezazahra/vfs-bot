import time
import logging
from abc import ABC, abstractmethod
from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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

    def _wait_for_page_load(self, timeout=30):
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except:
            pass

    def _is_cloudflare_challenge(self):
        """Check if the page is currently showing a Cloudflare challenge."""
        page_source = self.driver.page_source.lower()
        title = self.driver.title.lower()
        if "cloudflare" in title or "checking your browser" in page_source or "cf-challenge" in page_source:
            return True
        # Look for the Turnstile iframe or widget
        if self.driver.find_elements(By.XPATH, "//iframe[contains(@src, 'turnstile') or contains(@src, 'challenge')]"):
            return True
        if self.driver.find_elements(By.XPATH, "//div[contains(@class, 'cf-challenge') or contains(@class, 'turnstile')]"):
            return True
        return False

    def _bypass_cloudflare(self):
        if not self.url:
            raise ValueError("No URL provided.")
        logger.info(f"Navigating to {self.url}")
        # Open with reconnect (handles initial challenge)
        self.driver.uc_open_with_reconnect(self.url, reconnect_time=6)
        self._wait_for_page_load(10)

        # If still a challenge, retry multiple times
        max_retries = 4
        for attempt in range(max_retries):
            if self._is_cloudflare_challenge():
                logger.info(f"Cloudflare challenge detected (attempt {attempt+1}/{max_retries}).")
                try:
                    # SeleniumBase UC mode click
                    self.driver.uc_gui_click_captcha()
                    logger.info("CAPTCHA clicked using uc_gui_click_captcha().")
                    time.sleep(3)
                    # Check if solved
                    if not self._is_cloudflare_challenge():
                        logger.info("Cloudflare solved successfully!")
                        break
                except Exception as e:
                    logger.warning(f"uc_gui_click_captcha() failed: {e}")
                    # Fallback: try to click the checkbox via JavaScript
                    try:
                        self.driver.execute_script("""
                            var iframe = document.querySelector('iframe[src*="turnstile"]');
                            if (iframe) {
                                var doc = iframe.contentDocument || iframe.contentWindow.document;
                                var checkbox = doc.querySelector('.challenge-container input[type="checkbox"]');
                                if (checkbox) checkbox.click();
                            }
                        """)
                        logger.info("Tried to click CAPTCHA via JS fallback.")
                        time.sleep(3)
                    except:
                        pass
                    # If still challenge, refresh and try again
                    if self._is_cloudflare_challenge():
                        logger.warning("Challenge remains, refreshing page.")
                        self.driver.refresh()
                        self._wait_for_page_load(10)
                        continue
            else:
                logger.info("No Cloudflare challenge detected on this load.")
                break
        else:
            logger.warning("Cloudflare challenge not resolved after multiple attempts. Continuing anyway.")

        # Final wait for page to become interactive
        self._wait_for_page_load(10)

    def login(self):
        """Override in subclass. Should return True on success, False otherwise."""
        pass

    @abstractmethod
    def check_slots(self):
        """Override in subclass. Should return True if slots available."""
        pass

    def run_check(self):
        try:
            self._init_driver()
            self._bypass_cloudflare()
            login_success = self.login()
            if not login_success:
                return False, "Login failed."
            available = self.check_slots()
            msg = "✅ Slots AVAILABLE!" if available else "❌ No slots."
            return available, msg
        except Exception as e:
            logger.error(f"Error during check: {e}")
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