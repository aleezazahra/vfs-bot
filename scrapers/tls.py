import time
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from .base import BaseScraper

logger = logging.getLogger(__name__)

EMAIL_LOCATOR = (By.CSS_SELECTOR, "input[type='email'], input[name='email'], input#email, input#username, input[name='username']")
PASSWORD_LOCATOR = (By.CSS_SELECTOR, "input[type='password'], input[name='password'], input#password")
SUBMIT_LOCATOR = (By.CSS_SELECTOR, "button[type='submit'], input[type='submit'], button#submit")


class TLSScraper(BaseScraper):

    def _wait_ready(self, timeout=10):
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception:
            pass

    def _is_challenge_page(self):
        title = self.driver.title.lower()
        if "cloudflare" in title or "challenge" in title or "just a moment" in title:
            return True
        body_snippet = self.driver.page_source[:3000].lower()
        return "checking your browser" in body_snippet or "cf-challenge" in body_snippet

    def _try_switch_to_login_frame(self):
        self.driver.switch_to.default_content()
        iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
        for i in range(len(iframes)):
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            self.driver.switch_to.frame(iframes[i])
            found = self.driver.find_elements(*EMAIL_LOCATOR)
            if found:
                logger.info(f"Email field found inside iframe index {i}.")
                return True
            self.driver.switch_to.default_content()
        return False

    def _dismiss_cookie_banner(self):
        selectors = [
            "button.osano-cm-accept-all",
            "button.osano-cm-accept",
            "#onetrust-accept-btn-handler",
            "button[aria-label='Accept all']",
            "button[aria-label='Accept']",
        ]
        for sel in selectors:
            elements = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if elements:
                try:
                    elements[0].click()
                    logger.info(f"Dismissed cookie banner via {sel}.")
                    time.sleep(0.5)
                    return True
                except Exception:
                    try:
                        self.driver.execute_script("arguments[0].click();", elements[0])
                        logger.info(f"Dismissed cookie banner via JS click on {sel}.")
                        time.sleep(0.5)
                        return True
                    except Exception:
                        pass
        try:
            self.driver.execute_script(
                "document.querySelectorAll('.osano-cm-window, .osano-cm-dialog, #onetrust-consent-sdk').forEach(e => e.remove());"
            )
        except Exception:
            pass
        return False

    def _find_email_field(self, timeout=30):
        self.driver.switch_to.default_content()
        end_time = time.time() + timeout

        while time.time() < end_time:
            if self._is_challenge_page():
                logger.warning("Still on Cloudflare challenge page, waiting...")
                time.sleep(2)
                continue

            elements = self.driver.find_elements(*EMAIL_LOCATOR)
            if elements:
                logger.info("Email field found in main document.")
                return elements[0]

            if self._try_switch_to_login_frame():
                elements = self.driver.find_elements(*EMAIL_LOCATOR)
                if elements:
                    return elements[0]

            time.sleep(1)

        return None

    def login(self):
        if not self.username or not self.password:
            logger.info("No TLS credentials; skipping login.")
            return

        logger.info(f"TLS login URL: {self.driver.current_url}")
        self._wait_ready(10)

        logger.info(f"Page title: '{self.driver.title}'")
        logger.info(f"Current URL after load: {self.driver.current_url}")

        if self._is_challenge_page():
            logger.warning("Cloudflare page detected on initial load – waiting and retrying CAPTCHA.")
            time.sleep(5)
            try:
                self.driver.uc_gui_click_captcha()
                logger.info("uc_gui_click_captcha executed without raising.")
            except Exception as e:
                logger.warning(f"uc_gui_click_captcha failed: {e}")
            time.sleep(5)
            self.driver.refresh()
            self._wait_ready(10)
            logger.info(f"After refresh – title: '{self.driver.title}'")
            logger.info(f"After refresh – URL: {self.driver.current_url}")

        email_field = self._find_email_field(timeout=30)

        if email_field is None:
            logger.error("Email field NOT found after 30s. Saving debug info.")
            self.driver.switch_to.default_content()
            self.driver.save_screenshot("tls_email_not_found.png")
            with open("tls_page_source.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            raise Exception("Email field not found. Check tls_email_not_found.png and tls_page_source.html")

        email_field.clear()
        email_field.send_keys(self.username)
        time.sleep(0.5)

        password_elements = self.driver.find_elements(*PASSWORD_LOCATOR)
        if not password_elements:
            logger.error("Password field not found in same frame as email field.")
            self.driver.save_screenshot("tls_password_not_found.png")
            with open("tls_page_source.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            raise Exception("Password field not found. Check tls_password_not_found.png and tls_page_source.html")

        password_field = password_elements[0]
        password_field.clear()
        password_field.send_keys(self.password)
        time.sleep(0.5)

        self._dismiss_cookie_banner()

        submit_elements = self.driver.find_elements(*SUBMIT_LOCATOR)
        if submit_elements:
            try:
                submit_elements[0].click()
                logger.info("Login button clicked.")
            except Exception as e:
                logger.warning(f"Normal click intercepted ({e}); retrying with JS click.")
                self._dismiss_cookie_banner()
                self.driver.execute_script("arguments[0].click();", submit_elements[0])
                logger.info("Login button clicked via JS fallback.")
        else:
            try:
                form = self.driver.find_element(By.TAG_NAME, "form")
                self.driver.execute_script("arguments[0].submit();", form)
                logger.info("Form submitted via JS fallback.")
            except Exception:
                password_field.send_keys("\n")
                logger.info("Pressed Enter on password field.")

        self.driver.switch_to.default_content()
        logger.info("Login submitted. Waiting for redirect...")
        time.sleep(5)

    def check_slots(self):
        try:
            WebDriverWait(self.driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            page_source = self.driver.page_source.lower()
            if "no appointments" in page_source or "fully booked" in page_source:
                return False
            if "book appointment" in page_source or "available slots" in page_source:
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking TLS slots: {e}")
            return False