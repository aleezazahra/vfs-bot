import time
import logging
import json
import os
from abc import ABC, abstractmethod
from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from config import Config

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

    # ---------- Session persistence (cookies + localStorage) ----------
    def _session_file(self):
        name = self.__class__.__name__.lower()
        return os.path.join(Config.PROFILE_DIR, f"{name}_session.json")

    def _save_session(self):
        """Persist cookies + localStorage so future runs can skip login/OTP."""
        try:
            data = {
                "cookies": self.driver.get_cookies(),
                "local_storage": self.driver.execute_script(
                    "return JSON.stringify(window.localStorage);"
                ),
            }
            os.makedirs(Config.PROFILE_DIR, exist_ok=True)
            with open(self._session_file(), "w") as f:
                json.dump(data, f)
            logger.info(f"Session saved to {self._session_file()}")
        except Exception as e:
            logger.warning(f"Could not save session: {e}")

    def _load_session(self):
        """Restore a previously saved session onto the current driver."""
        if not self.url or not os.path.exists(self._session_file()):
            return False
        try:
            with open(self._session_file()) as f:
                data = json.load(f)
            # Must be on the domain before cookies can be added
            self.driver.get(self.url)
            self._wait_for_page_load(10)
            for cookie in data.get("cookies", []):
                try:
                    self.driver.add_cookie(cookie)
                except Exception:
                    continue
            ls = data.get("local_storage")
            if ls:
                try:
                    self.driver.execute_script(
                        "var ls = JSON.parse(arguments[0]);"
                        "window.localStorage.clear();"
                        "for (var k in ls) { window.localStorage.setItem(k, ls[k]); }",
                        ls,
                    )
                except Exception:
                    pass
            self.driver.refresh()
            self._wait_for_page_load(10)
            logger.info("Session loaded from file.")
            return True
        except Exception as e:
            logger.info(f"No usable saved session: {e}")
            return False

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
            self._load_session()
            self._bypass_cloudflare()
            login_success = self.login()
            if not login_success:
                return False, "Login failed."
            self._save_session()
            result = self.check_slots()
            if isinstance(result, tuple) and len(result) == 2:
                available, report = result
            else:
                available, report = bool(result), ""
            if available:
                msg = f"✅ Slots AVAILABLE!\n{report}"
            else:
                msg = f"❌ No slots.\n{report}"
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