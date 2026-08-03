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
            By.XPATH, "//select[contains(@name, 'center') or contains(@id, 'center') "
                      "or contains(@name, 'country') or contains(@id, 'country') "
                      "or contains(@name, 'selectedcountry') or contains(@id, 'selectedcountry') "
                      "or contains(@name, 'visa') or contains(@id, 'visa')]"
        )
        self.login_success_indicators = [
            "Reschedule Appointment",
            "Book Appointment",
            "My Applications",
            "Dashboard",
            "Logout",
        ]
        self.login_success_selectors = [
            (By.XPATH, "//a[contains(text(),'Logout')]"),
            (By.XPATH, "//button[contains(text(),'Logout')]"),
            (By.XPATH, "//a[contains(text(),'Sign Out')]"),
            (By.XPATH, "//button[contains(text(),'Sign Out')]"),
            (By.XPATH, "//a[contains(@href,'logout') or contains(@href,'signout')]"),
            (By.XPATH, "//span[contains(text(),'My Applications')]"),
            (By.XPATH, "//a[contains(text(),'My Applications')]"),
            (By.XPATH, "//a[contains(text(),'Book Appointment')]"),
            (By.XPATH, "//button[contains(text(),'Book Appointment')]"),
            (By.XPATH, "//a[contains(text(),'Reschedule Appointment')]"),
            (By.XPATH, "//button[contains(text(),'Reschedule Appointment')]"),
        ]
        self.login_error_keywords = [
            "invalid login credentials",
            "invalid credentials",
            "invalid email or password",
            "invalid username or password",
            "email or password is incorrect",
            "username or password is incorrect",
            "incorrect email",
            "incorrect password",
            "wrong password",
            "login failed",
            "authentication failed",
            "please check your credentials",
            "credentials are incorrect",
            "your account has been locked",
            "account has been locked",
            "too many login attempts",
            "too many attempts",
            "access denied",
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
            "all slots filled",
            "no availability",
            "no seat",
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

        # VFS EOI flow: after login you click the orange "Create Application"
        # button, which opens the appointment page with the dropdown menus.
        application_link_selectors = [
            (By.XPATH, "//button[contains(@class, 'btn-brand-orange')]"),
            (By.CSS_SELECTOR, "button.btn-brand-orange"),
            (By.XPATH, "//button[contains(text(),'Create Application')]"),
            (By.XPATH, "//button[contains(text(),'New Application')]"),
            (By.XPATH, "//a[contains(text(),'Create Application')]"),
            (By.XPATH, "//a[contains(text(),'New Application')]"),
            (By.XPATH, "//a[contains(text(),'Create an application')]"),
            (By.XPATH, "//a[contains(text(),'Start New Application')]"),
            (By.XPATH, "//a[contains(text(),'My Applications')]"),
            (By.XPATH, "//a[contains(@href, 'application')]"),
        ]
        for by, value in application_link_selectors:
            try:
                element = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((by, value))
                )
                element.click()
                logger.info(f"Clicked application link: {by}={value}")
                self._wait_for_page_load()
                self._human_delay(2, 4)
                self._switch_to_new_tab()
                # After creating an application we should now be on the
                # appointment/booking page – if not, try the appointment links.
                current_url = self.driver.current_url or ""
                if "appointment" in current_url or "booking" in current_url:
                    return True
                if self._find_country_dropdown(timeout=5) is not None:
                    return True
                for by2, value2 in appointment_link_selectors:
                    try:
                        el2 = WebDriverWait(self.driver, 3).until(
                            EC.element_to_be_clickable((by2, value2))
                        )
                        el2.click()
                        logger.info(f"Clicked appointment link: {by2}={value2}")
                        self._wait_for_page_load()
                        self._human_delay(2, 4)
                        return True
                    except:
                        continue
                return True
            except:
                continue

        logger.warning("Could not navigate to appointment page.")
        return False

    def _switch_to_new_tab(self):
        """If clicking opened a new browser tab, switch to it."""
        try:
            handles = self.driver.window_handles
            if len(handles) > 1:
                self.driver.switch_to.window(handles[-1])
                self._wait_for_page_load(10)
                self._human_delay(1, 2)
                logger.info(f"Switched to new tab: {self.driver.current_url}")
                return True
        except Exception:
            pass
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
    def _is_login_page(self):
        """Return True if the login form (email + password fields) is still visible."""
        try:
            email = self.driver.find_element(*self.username_selector)
            password = self.driver.find_element(*self.password_selector)
            return email.is_displayed() and password.is_displayed()
        except Exception:
            return False

    def _get_login_error(self):
        """Return the first VISIBLE login error message shown while the login
        form is still on screen, else None. Only meaningful during a failed
        login – once the form is gone the login has already succeeded."""
        if not self._is_login_page():
            return None
        error_container_selectors = [
            (By.XPATH, "//div[contains(@class, 'error') or contains(@class, 'alert') "
                       "or contains(@class, 'warning') or contains(@class, 'notification')]"),
            (By.XPATH, "//span[contains(@class, 'error') or contains(@class, 'alert')]"),
            (By.XPATH, "//p[contains(@class, 'error') or contains(@class, 'alert')]"),
            (By.XPATH, "//small[contains(@class, 'error')]"),
            (By.XPATH, "//li[contains(@class, 'error')]"),
            (By.TAG_NAME, "mat-error"),
            (By.TAG_NAME, "p-toast"),
        ]
        for by, value in error_container_selectors:
            try:
                for element in self.driver.find_elements(by, value):
                    if not element.is_displayed():
                        continue
                    text = (element.text or "").strip().lower()
                    if not text:
                        continue
                    for keyword in self.login_error_keywords:
                        if keyword in text:
                            return keyword
            except Exception:
                continue
        return None

    def _login_succeeded(self, driver=None):
        """Robustly determine whether the current page is a logged-in session.

        The primary signal is the state of the login form: if the email/password
        fields are still visible we are NOT logged in. Otherwise we look for an
        actual dashboard element. The URL is not trusted because VFS dashboard
        URLs frequently still contain '/login'."""
        driver = driver or self.driver
        if self._is_login_page():
            return False
        for by, value in self.login_success_selectors:
            try:
                element = driver.find_element(by, value)
                if element.is_displayed():
                    return True
            except Exception:
                continue
        page_source = driver.page_source or ""
        return any(ind in page_source for ind in self.login_success_indicators)

    def _is_logged_in(self):
        """Return True if the current page already looks like a logged-in session."""
        return self._login_succeeded()

    def _save_login_debug(self):
        """Save a screenshot + page source when login fails, for debugging."""
        try:
            self.driver.save_screenshot("vfs_login_fail.png")
            with open("vfs_login_page.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source or "")
            logger.info("Saved debug files: vfs_login_fail.png, vfs_login_page.html")
        except Exception as e:
            logger.warning(f"Could not save login debug files: {e}")

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
            logger.warning(
                "CAPTCHA could not be solved (no 2Captcha key / OCR failed). "
                "Submitting without CAPTCHA – VFS will likely reject the login. "
                "Set CAPTCHA_API_KEY in .env for reliable solving."
            )

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
                WebDriverWait(self.driver, 240).until(self._login_succeeded)
                logger.info("Login successful after OTP.")
                return True
            except TimeoutException:
                logger.warning("OTP not completed in time.")
                return False

        # Check login outcome
        page_source = (self.driver.page_source or "").lower()
        if self._is_login_page() and "the verification words are incorrect" in page_source:
            logger.warning("Incorrect CAPTCHA.")
            return False

        error_msg = self._get_login_error()
        if error_msg:
            logger.warning(f"Login failed: {error_msg}")
            self._save_login_debug()
            return False

        try:
            WebDriverWait(self.driver, 25).until(self._login_succeeded)
            logger.info("Login successful.")
            return True
        except TimeoutException:
            if self._is_login_page():
                logger.warning("Login failed – still on the login page (check your credentials).")
            else:
                logger.warning("Login unknown – could not confirm success.")
            self._save_login_debug()
            return False

    # ---------- Slot detection ----------
    def _extract_slot_info(self):
        """Extract the availability message (usually at the bottom of the page).

        Reads the *visible* page text so hidden templates / JS bundles never
        count as a slot message. Returns a positive slot string, "No slots
        available", or None if no availability message was found."""
        try:
            visible_text = self.driver.find_element(By.TAG_NAME, "body").text or ""
        except Exception:
            visible_text = ""
        page_source = self.driver.page_source or ""

        # Prefer visible text; fall back to raw source if body text is empty.
        matches = re.findall(self.slot_pattern, visible_text, re.IGNORECASE)
        if not matches and not visible_text.strip():
            matches = re.findall(self.slot_pattern, page_source, re.IGNORECASE)

        if matches:
            slot_messages = []
            for applicants, date in matches:
                slot_messages.append(f"{applicants} applicant(s): {date}")
            return " | ".join(slot_messages)

        check_text = visible_text.lower() if visible_text.strip() else page_source.lower()
        for phrase in self.slot_negative_keywords:
            if phrase in check_text:
                return "No slots available"
        return None

    def _matches_centre_filter(self, centre_name):
        if not self.centre:
            return True
        return self.centre.lower() in centre_name.lower()

    def _find_country_dropdown(self, timeout=15):
        """Locate the country/centre dropdown, with a fallback to any <select>."""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(self.center_dropdown_selector)
            )
        except Exception:
            pass
        try:
            for sel in self.driver.find_elements(By.TAG_NAME, "select"):
                if len(sel.find_elements(By.TAG_NAME, "option")) > 1:
                    return sel
        except Exception:
            pass
        return None

    def _select_option(self, dropdown, option_text):
        """Select a dropdown option by visible text (native + JS fallback)."""
        try:
            Select(dropdown).select_by_visible_text(option_text)
            return True
        except Exception:
            pass
        try:
            self.driver.execute_script("""
                var sel = arguments[0], text = arguments[1];
                for (var i = 0; i < sel.options.length; i++) {
                    if (sel.options[i].text.trim() === text) {
                        sel.selectedIndex = i;
                        break;
                    }
                }
                sel.dispatchEvent(new Event('change', {bubbles: true}));
                sel.dispatchEvent(new Event('input', {bubbles: true}));
            """, dropdown, option_text)
            return True
        except Exception:
            return False

    def _find_all_dropdowns(self):
        """Return every <select> element currently on the page."""
        try:
            return self.driver.find_elements(By.TAG_NAME, "select")
        except Exception:
            return []

    def _describe_dropdowns(self, dropdowns):
        """Log each dropdown's name/id and its options so we can tune selectors."""
        for i, sel in enumerate(dropdowns):
            try:
                opts = [o.text.strip() for o in sel.find_elements(By.TAG_NAME, "option")]
                name_id = " ".join([
                    (sel.get_attribute("name") or ""),
                    (sel.get_attribute("id") or ""),
                ]).strip().lower()
                logger.info(f"Dropdown #{i}: name/id={name_id!r}, {len(opts)} options")
                if opts:
                    preview = opts[:10]
                    suffix = " ..." if len(opts) > 10 else ""
                    logger.info(f"   options: {preview}{suffix}")
            except Exception:
                continue

    def _pick_main_dropdown(self, dropdowns):
        """Prefer the dropdown that looks like a country/centre picker."""
        for sel in dropdowns:
            try:
                name_id = " ".join([
                    (sel.get_attribute("name") or ""),
                    (sel.get_attribute("id") or ""),
                ]).lower()
            except Exception:
                continue
            if any(k in name_id for k in ("country", "centre", "center", "selectedcountry")):
                return sel
        return dropdowns[0] if dropdowns else None

    def _dropdown_at(self, index):
        """Re-locate a dropdown by its position (stale-element guard)."""
        try:
            dropdowns = self._find_all_dropdowns()
            if index < len(dropdowns):
                return dropdowns[index]
        except Exception:
            pass
        return None

    def _iterate_dropdown(self, dropdown):
        """Select every option in one dropdown and read the slot message.

        Returns (any_available, report_lines, meaningful) where `meaningful` is
        True if at least one selection produced a real availability message.
        """
        report_lines = []
        any_available = False
        meaningful = False

        try:
            option_texts = [o.text.strip() for o in Select(dropdown).options]
        except Exception:
            return any_available, report_lines, meaningful

        dropdowns = self._find_all_dropdowns()
        try:
            index = dropdowns.index(dropdown)
        except ValueError:
            index = 0

        placeholders = {
            "", "choose your application center", "select centre", "select center",
            "-- select --", "--", "select", "choose", "country", "select country",
            "please select", "please choose",
        }

        for centre_name in option_texts:
            if not centre_name or centre_name.lower() in placeholders:
                continue
            if not self._matches_centre_filter(centre_name):
                continue

            try:
                current = self._dropdown_at(index)
                if current is None:
                    break
                if not self._select_option(current, centre_name):
                    raise RuntimeError("could not select option")
                logger.info(f"Selected centre/country: {centre_name}")
                self._human_delay(1.2, 2.5)
                slot_info = self._extract_slot_info()
            except Exception as e:
                slot_info = f"Error selecting: {e}"

            if slot_info is None:
                slot_info = "No clear slot information found"
            elif slot_info == "No slots available":
                meaningful = True
            else:
                meaningful = True
                any_available = True

            report_lines.append(f"• {centre_name}: {slot_info}")

        return any_available, report_lines, meaningful

    def _check_all_centres(self):
        """Find the dropdown whose selections reveal slot availability.

        The VFS appointment page has multiple dropdown menus (country/centre,
        category, etc.). We try the country/centre-looking dropdown first, then
        the rest, and use the first one that produces a real availability
        message. Every dropdown's structure is logged for diagnostics.
        """
        dropdowns = self._find_all_dropdowns()
        if not dropdowns:
            return False, "No dropdown menus found on the appointment page."

        self._describe_dropdowns(dropdowns)

        preferred = self._pick_main_dropdown(dropdowns)
        candidates = dropdowns[:]
        if preferred is not None and preferred in candidates:
            candidates.remove(preferred)
        candidates.insert(0, preferred)

        for dropdown in candidates:
            if dropdown is None:
                continue
            any_available, report_lines, meaningful = self._iterate_dropdown(dropdown)
            if not meaningful or not report_lines:
                continue
            report = "\n".join(report_lines)
            logger.info(f"Slot report:\n{report}")
            return any_available, report

        return False, "No slot information found after trying all dropdowns."

    def _save_slot_debug(self):
        """Save a screenshot + page source when slot checking fails, for debugging."""
        try:
            self.driver.save_screenshot("vfs_slot_check_fail.png")
            with open("vfs_slot_page.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source or "")
            logger.info("Saved debug files: vfs_slot_check_fail.png, vfs_slot_page.html")
        except Exception as e:
            logger.warning(f"Could not save slot debug files: {e}")

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
                available, report = self._check_all_centres()
                if "No dropdown menus" in report or "No slot information" in report:
                    logger.warning(report)
                    self._save_slot_debug()
                return available, report
            except TimeoutException:
                logger.info("No dropdown found; checking current page.")
                self._save_slot_debug()
                return self._check_current_page()

        except Exception as e:
            logger.error(f"Error checking slots: {e}")
            return False, f"Error checking slots: {str(e)}"
