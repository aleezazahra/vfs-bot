import time
import random
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
    def __init__(self, username=None, password=None, url=None, headless=False,
                 appointment_url=None, centre=None):
        super().__init__(username, password, url, headless)
        self.appointment_url = appointment_url
        self.centre = centre

        # VFS-specific selectors (Angular/React version)
        self.username_selector = (By.ID, "email")
        self.password_selector = (By.ID, "password")
        self.captcha_input_selector = (By.ID, "CaptchaInputText")
        self.captcha_image_selector = (By.ID, "CaptchaImage")
        self.login_button_selectors = [
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
        self.center_dropdown_selector = (
            By.XPATH, "//select[contains(@name, 'center') or contains(@id, 'center')]"
        )
        self.login_success_indicators = [
            "Reschedule Appointment",
            "Book Appointment",
            "My Applications",
            "Dashboard",
            "Logout",
        ]
        self.otp_input_selectors = [
            (By.ID, "otp"),
            (By.ID, "OtpInput"),
            (By.ID, "otpCode"),
            (By.ID, "verificationCode"),
            (By.NAME, "otp"),
            (By.NAME, "code"),
            (By.CSS_SELECTOR, "input[autocomplete='one-time-code']"),
            (By.XPATH, "//input[contains(@name, 'otp') or contains(@id, 'otp')]"),
            (By.XPATH, "//input[contains(@placeholder, 'OTP') or contains(@placeholder, 'verification')]"),
        ]
        self.slot_negative_keywords = [
            "no appointments available",
            "no open seats",
            "there are no open seats available",
            "fully booked",
            "no slots",
            "unavailable",
            "all slots filled",
            "no availability",
        ]
        self.slot_pattern = r"Earliest\s+available\s+slot\s+for\s+(\d+)\s*applicants?\s*is\s*:?\s*(\d{2}-\d{2}-\d{4})"

    # ---------- Helper: random human-like delay ----------
    def _human_delay(self, min_sec=0.5, max_sec=1.5):
        time.sleep(random.uniform(min_sec, max_sec))

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
                self._human_delay(0.5, 1)
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
                self._human_delay(0.5, 1)
                return
            except:
                continue

    # ---------- Navigate to appointment page ----------
    def _navigate_to_appointment_page(self):
        current_url = self.driver.current_url or ""
        if self.appointment_url:
            logger.info(f"Navigating to appointment URL: {self.appointment_url}")
            self.driver.get(self.appointment_url)
            self._wait_for_page_load()
            self._human_delay(2, 4)
            return True

        if "appointment" in current_url or "booking" in current_url:
            logger.info("Already on an appointment page.")
            return True

        # Fallback: look for a booking/appointment link on the dashboard
        appointment_link_selectors = [
            (By.XPATH, "//a[contains(text(),'Book Appointment')]"),
            (By.XPATH, "//a[contains(text(),'Book an appointment')]"),
            (By.XPATH, "//a[contains(text(),'Schedule Appointment')]"),
            (By.XPATH, "//a[contains(text(),'Reschedule Appointment')]"),
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
                self._wait_for_page_load()
                self._human_delay(2, 4)
                return True
            except:
                continue

        logger.warning("Could not navigate to appointment page.")
        return False

    # ---------- CAPTCHA methods ----------
    def _find_captcha_image(self):
        try:
            img = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(self.captcha_image_selector)
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
    def _is_logged_in(self):
        """Return True if the current page already looks like a logged-in session."""
        current_url = (self.driver.current_url or "").lower()
        if "login" in current_url or "signin" in current_url:
            return False
        page_source = self.driver.page_source or ""
        return any(ind in page_source for ind in self.login_success_indicators)

    def _find_otp_field(self, timeout=8):
        for by, value in self.otp_input_selectors:
            try:
                return WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((by, value))
                )
            except:
                continue
        return None

    def login(self):
        if not self.username or not self.password:
            logger.info("No credentials; skipping login.")
            return False

        # Reuse a persisted session if still valid
        if self._is_logged_in():
            logger.info("Already logged in (session persisted).")
            return True

        logger.info(f"VFS login URL: {self.url}")

        self._accept_cookies()
        self._human_delay(0.5, 1)

        # Email
        try:
            email_field = WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located(self.username_selector)
            )
        except Exception as e:
            logger.error(f"Email field not found: {e}")
            return False

        email_field.clear()
        email_field.send_keys(self.username)
        self._human_delay(0.5, 1)

        # Password
        try:
            password_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(self.password_selector)
            )
        except Exception as e:
            logger.error(f"Password field not found: {e}")
            return False
        password_field.clear()
        password_field.send_keys(self.password)
        self._human_delay(0.5, 1)

        # CAPTCHA
        captcha_text = self._solve_captcha()
        if captcha_text:
            try:
                captcha_input = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(self.captcha_input_selector)
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
        for by, value in self.login_button_selectors:
            try:
                btn = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((by, value))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                self._human_delay(0.3, 0.8)
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

        self._human_delay(3, 5)

        # Check for OTP / email-verification step
        otp_field = self._find_otp_field(5)
        if otp_field:
            logger.warning(
                "OTP verification required. Enter the code in the browser "
                "window (first-time setup only – the session is then saved)."
            )
            try:
                WebDriverWait(self.driver, 240).until(
                    lambda d: any(ind in (d.page_source or "")
                                  for ind in self.login_success_indicators)
                )
                logger.info("Login successful after OTP.")
                return True
            except TimeoutException:
                logger.warning("OTP not completed in time.")
                return False

        # Check login outcome (wait for a dashboard indicator to appear)
        page_source = self.driver.page_source
        if "The verification words are incorrect" in page_source:
            logger.warning("Incorrect CAPTCHA.")
            return False
        elif "Your account has been locked" in page_source:
            logger.warning("Account locked.")
            return False

        try:
            WebDriverWait(self.driver, 25).until(
                lambda d: any(ind in d.page_source for ind in self.login_success_indicators)
            )
            logger.info("Login successful.")
            return True
        except TimeoutException:
            logger.warning("Login unknown – dashboard indicators not found.")
            return False

    # ---------- Slot detection ----------
    def _extract_slot_info(self):
        """Extract 'Earliest available slot' messages from the current page."""
        page_source = self.driver.page_source
        matches = re.findall(self.slot_pattern, page_source, re.IGNORECASE)
        if matches:
            slot_messages = []
            for applicants, date in matches:
                slot_messages.append(f"{applicants} applicant(s): {date}")
            return " | ".join(slot_messages)
        else:
            page_lower = page_source.lower()
            for phrase in self.slot_negative_keywords:
                if phrase in page_lower:
                    return "No slots available"
            return None

    def _matches_centre_filter(self, centre_name):
        if not self.centre:
            return True
        return self.centre.lower() in centre_name.lower()

    def _check_all_centres(self):
        """Loop over every centre in the dropdown and report slots for each."""
        report_lines = []
        any_available = False

        dropdown = WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located(self.center_dropdown_selector)
        )
        select = Select(dropdown)
        options = select.options

        placeholders = {"", "choose your application center", "select centre", "select center", "-- select --"}
        for option in options:
            centre_name = option.text.strip()
            if not centre_name or centre_name.lower() in placeholders:
                continue
            if not self._matches_centre_filter(centre_name):
                continue

            try:
                select.select_by_visible_text(centre_name)
                logger.info(f"Selected centre: {centre_name}")
                self._human_delay(1.5, 3)
                slot_info = self._extract_slot_info()
            except Exception as e:
                slot_info = f"Error selecting: {e}"

            if slot_info is None:
                slot_info = "No clear slot information found"
            elif slot_info == "No slots available":
                slot_info = "No slots available"
            else:
                any_available = True

            report_lines.append(f"• {centre_name}: {slot_info}")

            # Re-locate dropdown after AJAX update (stale element guard)
            try:
                dropdown = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located(self.center_dropdown_selector)
                )
                select = Select(dropdown)
            except:
                break

        if not report_lines:
            return False, "No centres available on the appointment page."

        report = "\n".join(report_lines)
        logger.info(f"Slot report:\n{report}")
        return any_available, report

    def _check_current_page(self):
        slot_info = self._extract_slot_info()
        if slot_info is None:
            return False, "No slot information found on the page."
        if slot_info == "No slots available":
            return False, "No slots available."
        return True, slot_info

    def check_slots(self):
        """
        Login already done. Navigate to the appointment page, then check slots for
        every centre/country available. Returns (available: bool, report: str).
        """
        try:
            WebDriverWait(self.driver, 20).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            self._dismiss_demo_notice()
            self._human_delay(0.5, 1)

            self._navigate_to_appointment_page()

            WebDriverWait(self.driver, 20).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            self._dismiss_demo_notice()

            try:
                return self._check_all_centres()
            except TimeoutException:
                logger.info("No centre dropdown found; checking current page.")
                return self._check_current_page()

        except Exception as e:
            logger.error(f"Error checking slots: {e}")
            return False, f"Error checking slots: {str(e)}"
