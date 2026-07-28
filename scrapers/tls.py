import time
import random
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from .base import BaseScraper

logger = logging.getLogger(__name__)

class TLSScraper(BaseScraper):

    def _human_delay(self):
        time.sleep(random.uniform(0.5, 1.5))

    def _force_set_password(self, password_field):
        """Clone and replace the password field to remove event listeners."""
        self.driver.execute_script("""
            var field = arguments[0];
            var newVal = arguments[1];
            var clone = field.cloneNode(true);
            field.parentNode.replaceChild(clone, field);
            clone.value = newVal;
            clone.dispatchEvent(new Event('input', { bubbles: true }));
            clone.dispatchEvent(new Event('change', { bubbles: true }));
            return clone;
        """, password_field, self.password)

    def login(self):
        if not self.username or not self.password:
            logger.info("No TLS credentials; skipping login.")
            return False

        logger.info(f"TLS login URL: {self.driver.current_url}")

        # Wait for the email field – up to 60 seconds with refresh retry
        try:
            email_field = WebDriverWait(self.driver, 60).until(
                EC.presence_of_element_located((By.ID, "email"))
            )
            logger.info("Email field found.")
        except Exception as e:
            logger.warning(f"Email field not found: {e}. Refreshing and retrying.")
            self.driver.refresh()
            self._human_delay()
            try:
                self.driver.uc_gui_click_captcha()
            except:
                pass
            self._human_delay()
            try:
                email_field = WebDriverWait(self.driver, 60).until(
                    EC.presence_of_element_located((By.ID, "email"))
                )
                logger.info("Email field found after refresh.")
            except Exception as e2:
                self.driver.save_screenshot("tls_email_not_found.png")
                with open("tls_page_source.html", "w", encoding="utf-8") as f:
                    f.write(self.driver.page_source)
                logger.error("Email field still missing. Check screenshot and HTML.")
                return False

        # Fill email
        email_field.clear()
        email_field.send_keys(self.username)
        self._human_delay()

        # ---------- Password (clone-and-replace) ----------
        try:
            password_field = self.driver.find_element(By.ID, "password")
            password_field.click()
            self._human_delay()
            self._force_set_password(password_field)
            # Re-locate and verify
            password_field = self.driver.find_element(By.ID, "password")
            if password_field.get_attribute('value') != self.password:
                logger.warning("Password value mismatch, re-setting via direct JS.")
                self.driver.execute_script("arguments[0].value = arguments[1];", password_field, self.password)
            else:
                logger.info("Password set successfully.")
        except Exception as e:
            logger.error(f"Password field not found or setting failed: {e}")
            return False
        self._human_delay()

        # ---------- No image CAPTCHA solving – assume none or handled by Cloudflare ----------
        # If the page unexpectedly shows an image CAPTCHA, we could add a simple OCR here,
        # but for now we skip it. The site may not have one after Cloudflare.

        # Click login button
        try:
            login_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "submit"))
            )
            login_btn.click()
            logger.info("Login button clicked.")
        except Exception as e:
            logger.warning(f"Normal click failed: {e}, trying JS click.")
            try:
                login_btn = self.driver.find_element(By.ID, "submit")
                self.driver.execute_script("arguments[0].click();", login_btn)
            except:
                logger.warning("JS click failed, using ActionChains.")
                try:
                    actions = ActionChains(self.driver)
                    actions.move_to_element(login_btn).click().perform()
                except:
                    logger.warning("All clicks failed – submitting form via Enter.")
                    password_field.send_keys("\n")

        logger.info("Login submitted. Waiting for redirect...")
        time.sleep(5)

        # Check if login succeeded
        page_source = self.driver.page_source
        # Common success indicators (adjust to your TLS site)
        success_indicators = ["Dashboard", "My appointments", "Logout", "Book appointment"]
        if any(ind in page_source for ind in success_indicators):
            logger.info("Login successful!")
            return True
        else:
            # If page shows the login form again, it's a failure
            if "email" in page_source.lower() and "password" in page_source.lower():
                logger.warning("Login form still present – likely failed.")
            else:
                logger.warning("Unknown page after login – may have succeeded but not detected.")
            self.driver.save_screenshot("tls_login_fail.png")
            return False

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
            logger.error(f"Error checking slots: {e}")
            return False