import logging
from .base import BaseScraper
import time 
logger = logging.getLogger(__name__)

class BLSScraper(BaseScraper):
    """BLS International specific scraper."""

    def login(self):
        if not self.username or not self.password:
            logger.info("No BLS credentials provided; skipping login.")
            return
        try:
            # Adjust selectors to BLS login.
            username_field = self.driver.find_element("name", "email")
            password_field = self.driver.find_element("name", "password")
            username_field.send_keys(self.username)
            password_field.send_keys(self.password)
            login_btn = self.driver.find_element("xpath", "//input[@type='submit']")
            login_btn.click()
            time.sleep(3)
            logger.info("BLS login submitted.")
        except Exception as e:
            logger.warning(f"BLS login failed: {e}")

    def check_slots(self):
        try:
            page_source = self.driver.page_source.lower()
            if "no appointments available" in page_source or "slots full" in page_source:
                return False
            if "book appointment" in page_source or "available slots" in page_source:
                return True
            return not ("no slot" in page_source)
        except Exception as e:
            logger.error(f"Error checking BLS slots: {e}")
            return False