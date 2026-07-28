import time
import logging
import io
import base64
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
from .base import BaseScraper
from config import Config

logger = logging.getLogger(__name__)

class VFSScraper(BaseScraper):
    USERNAME_SELECTOR = (By.ID, "email")
    PASSWORD_SELECTOR = (By.ID, "password")
    CAPTCHA_INPUT_SELECTOR = (By.ID, "CaptchaInputText")
    LOGIN_SUCCESS_INDICATOR = "Reschedule Appointment"

    # Updated button selectors (Angular VFS uses label="Sign In")
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
                logger.error(f"2Captcha error: {result.get('request')}")
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
                    logger.error(f"2Captcha error: {poll_result.get('request')}")
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
            self.driver.save_screenshot("vfs_captcha_not_found.png")
            with open("vfs_page_source.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
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

    def login(self):
        if not self.username or not self.password:
            logger.info("No credentials; skipping login.")
            return False

        logger.info(f"VFS login URL: {self.driver.current_url}")

        # Accept cookies
        self._accept_cookies()
        time.sleep(1)

        # Email
        try:
            email_field = WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located(self.USERNAME_SELECTOR)
            )
        except Exception as e:
            logger.error(f"Email field not found: {e}")
            self.driver.save_screenshot("vfs_email_not_found.png")
            with open("vfs_page_source.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
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
                self.driver.save_screenshot("vfs_captcha_input_error.png")
                return False
        else:
            logger.warning("No CAPTCHA text – skipping fill.")

        # Click the Sign In button
        button_clicked = False
        for by, value in self.LOGIN_BUTTON_SELECTORS:
            try:
                btn = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((by, value))
                )
                # Scroll to button
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(0.5)
                # Try normal click, fallback to JavaScript
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
                # Last resort: press Enter on captcha input
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
            logger.warning("Login unknown. Saving screenshot.")
            self.driver.save_screenshot("vfs_login_unknown.png")
            return False

    def check_slots(self):
        try:
            WebDriverWait(self.driver, 30).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            page_source = self.driver.page_source.lower()
            if "there are no open seats available" in page_source:
                logger.info("No appointments available.")
                return False
            else:
                logger.info("Potential slots available.")
                return True
        except Exception as e:
            logger.error(f"Error checking slots: {e}")
            return False