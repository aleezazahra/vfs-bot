import time
import logging
import io
import base64
import re
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from PIL import Image
from .base import BaseScraper
from config import Config

logger = logging.getLogger(__name__)

class VFSScraper(BaseScraper):
    # ---------- Login selectors ----------
    USERNAME_SELECTOR = (By.ID, "email")
    PASSWORD_SELECTOR = (By.ID, "password")
    CAPTCHA_INPUT_SELECTOR = (By.ID, "CaptchaInputText")
    LOGIN_SUCCESS_INDICATOR = "Reschedule Appointment"

    LOGIN_BUTTON_SELECTORS = [
        (By.XPATH, "//button[@label='Sign In']"),
        (By.CSS_SELECTOR, "button[label='Sign In']"),
        (By.XPATH, "//button[contains(@class, 'btn-brand-orange')]"),
        (By.XPATH, "//button[contains(@class, 'mat-stroked-button')][contains(text(), 'Sign In')]"),
        (By.CSS_SELECTOR, "input[type='submit'][value='Continue']"),
        (By.CSS_SELECTOR, "input[value='Continue']"),
        (By.XPATH, "//button[contains(text(),'Continue')]"),
        (By.XPATH, "//input[@type='submit']"),
        (By.XPATH, "//button[@type='submit']"),
        (By.XPATH, "//button[contains(@class, 'submit')]"),
    ]

    CAPTCHA_IMAGE_SELECTOR = (By.ID, "CaptchaImage")

    # ---------- Appointment page URL (optional) ----------
    APPOINTMENT_URL = None  # e.g., "https://visa.vfsglobal.com/usa/en/eoi/appointment"

    # ---------- Center dropdown selectors ----------
    CENTER_DROPDOWN_SELECTOR = (By.XPATH, "//select[contains(@name, 'center') or contains(@id, 'center')]")

    # ---------- Slot detection keywords ----------
    SLOT_NEGATIVE_KEYWORDS = [
        "no appointments available",
        "no open seats",
        "there are no open seats available",
        "fully booked",
        "no slots",
        "unavailable",
        "all slots filled",
        "no availability",
    ]

    # ---------- Cookie acceptance ----------
    def _accept_cookies(self):
        cookie_selectors = [
            (By.XPATH, "//button[contains(text(),'Accept')]"),
            (By.XPATH, "//button[contains(text(),'Accept all')]"),
            (By.XPATH, "//button[contains(text(),'I agree')]"),
            (By.XPATH, "//button[contains(text(),'OK')]"),
            (By.XPATH, "//button[contains(@class, 'cookie')]"),
            (By.ID, "cookie-accept"),
        ]
        for by, value in cookie_selectors:
            try:
                btn = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((by, value))
                )
                btn.click()
                logger.info(f"Cookie accepted: {by}={value}")
                time.sleep(0.5)
                return
            except:
                continue

    # ---------- Dismiss demo notice ----------
    def _dismiss_demo_notice(self):
        dismiss_selectors = [
            (By.XPATH, "//button[contains(text(),'Dismiss')]"),
            (By.XPATH, "//button[contains(text(),'Close')]"),
            (By.XPATH, "//button[contains(text(),'OK')]"),
            (By.CSS_SELECTOR, ".btn-dismiss"),
            (By.CLASS_NAME, "close"),
        ]
        for by, value in dismiss_selectors:
            try:
                btn = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((by, value))
                )
                btn.click()
                logger.info(f"Dismissed demo notice with selector: {by}={value}")
                time.sleep(0.5)
                return
            except:
                continue

    # ---------- Navigate to appointment page ----------
    def _navigate_to_appointment_page(self):
        if self.APPOINTMENT_URL:
            logger.info(f"Navigating to appointment URL: {self.APPOINTMENT_URL}")
            self.driver.get(self.APPOINTMENT_URL)
            time.sleep(5)
            return True

        # Fallback: look for "Book Appointment" link
        appointment_link_selectors = [
            (By.XPATH, "//a[contains(text(),'Book Appointment')]"),
            (By.XPATH, "//a[contains(text(),'Schedule Appointment')]"),
            (By.XPATH, "//button[contains(text(),'Book Appointment')]"),
            (By.XPATH, "//a[contains(@href, 'appointment')]"),
            (By.XPATH, "//a[contains(@href, 'booking')]"),
        ]
        for by, value in appointment_link_selectors:
            try:
                element = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((by, value))
                )
                element.click()
                logger.info(f"Clicked appointment link: {by}={value}")
                time.sleep(5)
                return True
            except:
                continue

        logger.warning("Could not navigate to appointment page.")
        return False

    # ---------- CAPTCHA methods ----------
    def _find_captcha_image(self):
        try:
            img = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(self.CAPTCHA_IMAGE_SELECTOR)
            )
            return img
        except:
            fallbacks = [
                (By.XPATH, "//img[contains(@src, 'captcha')]"),
                (By.XPATH, "//img[contains(@id, 'Captcha')]"),
                (By.XPATH, "//form//img[contains(@src, '.png')]"),
            ]
            for by, val in fallbacks:
                try:
                    img = WebDriverWait(self.driver, 3).until(
                        EC.presence_of_element_located((by, val))
                    )
                    if img.size['width'] > 30 and img.size['height'] > 30:
                        return img
                except:
                    continue
            return None

    def _solve_captcha_2captcha(self, captcha_img):
        api_key = getattr(Config, 'CAPTCHA_API_KEY', None)
        if not api_key:
            logger.warning("No 2Captcha API key.")
            return None
        try:
            location = captcha_img.location
            size = captcha_img.size
            png = self.driver.get_screenshot_as_png()
            img = Image.open(io.BytesIO(png))
            left, top = location['x'], location['y']
            right = left + size['width']
            bottom = top + size['height']
            captcha_crop = img.crop((left, top, right, bottom))
            buffered = io.BytesIO()
            captcha_crop.save(buffered, format="PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

            payload = {'key': api_key, 'method': 'base64', 'body': img_base64, 'json': 1}
            response = requests.post('https://2captcha.com/in.php', data=payload, timeout=30)
            result = response.json()
            if result.get('status') != 1:
                logger.error(f"2Captcha submit error: {result.get('request')}")
                return None
            captcha_id = result['request']
            for _ in range(20):
                time.sleep(5)
                poll_resp = requests.get(
                    'https://2captcha.com/res.php',
                    params={'key': api_key, 'action': 'get', 'id': captcha_id, 'json': 1}
                )
                poll_result = poll_resp.json()
                if poll_result.get('status') == 1:
                    text = poll_result['request']
                    logger.info(f"2Captcha solved: '{text}'")
                    return text
                elif poll_result.get('request') == 'CAPCHA_NOT_READY':
                    continue
                else:
                    logger.error(f"2Captcha poll error: {poll_result.get('request')}")
                    return None
            logger.error("2Captcha timeout")
            return None
        except Exception as e:
            logger.error(f"2Captcha exception: {e}")
            return None

    def _solve_captcha_tesseract(self, captcha_img):
        try:
            import pytesseract
            location = captcha_img.location
            size = captcha_img.size
            png = self.driver.get_screenshot_as_png()
            img = Image.open(io.BytesIO(png))
            left, top = location['x'], location['y']
            right = left + size['width']
            bottom = top + size['height']
            captcha_crop = img.crop((left, top, right, bottom))
            text = pytesseract.image_to_string(captcha_crop, config='--psm 8').strip()
            return text if len(text) >= 2 else None
        except Exception as e:
            logger.warning(f"OCR failed: {e}")
            return None

    def _solve_captcha(self):
        captcha_img = self._find_captcha_image()
        if not captcha_img:
            logger.error("CAPTCHA image not found.")
            return None

        text = self._solve_captcha_2captcha(captcha_img)
        if text:
            return text

        text = self._solve_captcha_tesseract(captcha_img)
        if text:
            return text

        logger.error("All CAPTCHA solving methods failed.")
        return None

    # ---------- Login ----------
    def login(self):
        if not self.username or not self.password:
            logger.info("No credentials; skipping login.")
            return False

        logger.info(f"VFS login URL: {self.driver.current_url}")

        self._accept_cookies()
        time.sleep(1)

        # Email
        try:
            email_field = WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located(self.USERNAME_SELECTOR)
            )
        except Exception as e:
            logger.error(f"Email field not found: {e}")
            return False

        email_field.clear()
        email_field.send_keys(self.username)
        time.sleep(1)

        # Password
        try:
            password_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(self.PASSWORD_SELECTOR)
            )
        except Exception as e:
            logger.error(f"Password field not found: {e}")
            return False
        password_field.clear()
        password_field.send_keys(self.password)
        time.sleep(1)

        # CAPTCHA
        captcha_text = self._solve_captcha()
        if captcha_text:
            try:
                captcha_input = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(self.CAPTCHA_INPUT_SELECTOR)
                )
                captcha_input.clear()
                captcha_input.send_keys(captcha_text)
                logger.info("CAPTCHA filled.")
            except Exception as e:
                logger.error(f"CAPTCHA input field not found: {e}")
                return False
        else:
            logger.warning("No CAPTCHA text – skipping fill.")

        # Click Sign In
        button_clicked = False
        for by, value in self.LOGIN_BUTTON_SELECTORS:
            try:
                btn = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((by, value))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(0.5)
                try:
                    btn.click()
                except:
                    self.driver.execute_script("arguments[0].click();", btn)
                    logger.info("Used JavaScript click.")
                logger.info(f"Clicked button with selector: {by}={value}")
                button_clicked = True
                break
            except Exception as e:
                logger.debug(f"Selector {by}={value} failed: {e}")
                continue

        if not button_clicked:
            try:
                captcha_input.send_keys("\n")
                logger.info("Pressed Enter on captcha input.")
            except:
                try:
                    form = self.driver.find_element(By.TAG_NAME, "form")
                    self.driver.execute_script("arguments[0].submit();", form)
                    logger.info("Submitted form via JavaScript.")
                except Exception as e:
                    logger.error(f"All submit methods failed: {e}")
                    return False

        time.sleep(5)

        # Check login outcome
        page_source = self.driver.page_source
        if self.LOGIN_SUCCESS_INDICATOR in page_source:
            logger.info("Login successful.")
            return True
        elif "The verification words are incorrect" in page_source:
            logger.warning("Incorrect CAPTCHA.")
            return False
        elif "Your account has been locked" in page_source:
            logger.warning("Account locked.")
            return False
        else:
            logger.warning("Login unknown.")
            return False

    # ---------- Helper: get slot info from current page ----------
    def _extract_slot_info(self):
        """Extract all 'Earliest available slot' messages from the current page."""
        page_source = self.driver.page_source
        slot_pattern = r"Earliest available slot for (\d+) applicants? is : (\d{2}-\d{2}-\d{4})"
        matches = re.findall(slot_pattern, page_source, re.IGNORECASE)
        if matches:
            slot_messages = []
            for applicants, date in matches:
                slot_messages.append(f"  {applicants} applicant(s): {date}")
            return "\n".join(slot_messages)
        else:
            # Check for negative keywords
            page_lower = page_source.lower()
            for phrase in self.SLOT_NEGATIVE_KEYWORDS:
                if phrase in page_lower:
                    return "No slots available"
            return None  # unknown

    # ---------- Main slot check: loop over all centers ----------
    def check_slots(self):
        """
        Loop through all centers in the dropdown, extract slot info for each.
        Returns (available, report_message) where available is True if ANY center has slots.
        """
        try:
            # Wait for page load
            WebDriverWait(self.driver, 20).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            # Dismiss demo notice
            self._dismiss_demo_notice()
            time.sleep(1)

            # Navigate to appointment page if needed
            current_url = self.driver.current_url
            if "appointment" not in current_url and "booking" not in current_url:
                self._navigate_to_appointment_page()

            # Wait for page to be ready
            WebDriverWait(self.driver, 20).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            # Locate the center dropdown
            try:
                dropdown = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located(self.CENTER_DROPDOWN_SELECTOR)
                )
            except Exception as e:
                logger.error(f"Center dropdown not found: {e}")
                return False, "Center dropdown not found on the page."

            # Get all options
            select = Select(dropdown)
            options = select.options
            if len(options) <= 1:
                logger.warning("No center options found (only placeholder).")
                return False, "No centers available."

            # Prepare report
            report_lines = []
            any_available = False

            # Loop over options, skip placeholder (usually first with empty value)
            for idx, option in enumerate(options):
                center_name = option.text.strip()
                if not center_name or center_name.lower() == "choose your application center":
                    continue

                # Select this option
                try:
                    select.select_by_visible_text(center_name)
                    logger.info(f"Selected center: {center_name}")
                    time.sleep(2)  # allow page to update via AJAX
                    # Wait for the slot info to update (or a loading indicator to disappear)
                    # We'll just wait for the page to be 'stable' – you can add a specific wait if needed.
                except Exception as e:
                    logger.warning(f"Failed to select center '{center_name}': {e}")
                    report_lines.append(f"Center: {center_name}  →  Error selecting")
                    continue

                # Extract slot info for this center
                slot_info = self._extract_slot_info()
                if slot_info is None:
                    slot_info = "No clear slot information found"
                elif "No slots" in slot_info or "no appointments" in slot_info.lower():
                    slot_info = "No slots available"
                else:
                    any_available = True

                report_lines.append(f"Center: {center_name}\n{slot_info}")
                report_lines.append("")  # blank line separator

            if not report_lines:
                return False, "No centers processed."

            report = "\n".join(report_lines).strip()
            logger.info(f"Slot report:\n{report}")

            return any_available, report

        except Exception as e:
            logger.error(f"Error in check_slots: {e}")
            return False, f"Error checking slots: {str(e)}"