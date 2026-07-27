import time
import logging
import io
import base64
import cv2
import numpy as np
import pytesseract
import re
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
from .base import BaseScraper
from config import Config

logger = logging.getLogger(__name__)

class VFSScraper(BaseScraper):
    USERNAME_SELECTOR = (By.ID, "EmailId")
    PASSWORD_SELECTOR = (By.ID, "Password")
    CAPTCHA_INPUT_SELECTOR = (By.ID, "CaptchaInputText")
    LOGIN_BUTTON_SELECTOR = (By.CSS_SELECTOR, "input[type='submit'][value='Continue']")
    CAPTCHA_IMAGE_SELECTOR = (By.ID, "CaptchaImage")
    LOGIN_SUCCESS_INDICATOR = "Reschedule Appointment"
    MAX_WAIT = 600

    def _find_captcha_image(self):
        try:
            img = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(self.CAPTCHA_IMAGE_SELECTOR)
            )
            logger.info("CAPTCHA image found.")
            return img
        except Exception:
            fallback_selectors = [
                (By.XPATH, "//img[contains(@src, 'captcha')]"),
                (By.XPATH, "//img[contains(@id, 'Captcha')]"),
                (By.XPATH, "//form//img[contains(@src, '.png')]"),
            ]
            for by, val in fallback_selectors:
                try:
                    img = WebDriverWait(self.driver, 3).until(
                        EC.presence_of_element_located((by, val))
                    )
                    if img.size['width'] > 30 and img.size['height'] > 30:
                        logger.info(f"CAPTCHA found with fallback: {by}={val}")
                        return img
                except:
                    continue
            logger.error("No CAPTCHA image found.")
            return None

    def _solve_captcha_2captcha(self, captcha_img):
        api_key = getattr(Config, 'CAPTCHA_API_KEY', None)
        if not api_key:
            logger.warning("No 2Captcha API key configured.")
            return None

        logger.info(f"Using 2Captcha (key ending ...{api_key[-4:]})")
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
                    params={'key': api_key, 'action': 'get', 'id': captcha_id, 'json': 1},
                    timeout=15,
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
            with open("captcha.png", "wb") as f:
                f.write(captcha_img.screenshot_as_png)

            image = cv2.imread("captcha.png")
            if image is None:
                logger.error("Failed to read captcha.png for Tesseract")
                return None
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            image = cv2.copyMakeBorder(image, 5, 5, 5, 5, cv2.BORDER_CONSTANT, value=[250])
            image = cv2.filter2D(image, -1, np.ones((4, 4), np.float32) / 16)

            se = cv2.getStructuringElement(cv2.MORPH_RECT, (8, 8))
            bg = cv2.morphologyEx(image, cv2.MORPH_DILATE, se)
            image = cv2.divide(image, bg, scale=255)
            image = cv2.filter2D(image, -1, np.ones((3, 4), np.float32) / 12)
            image = cv2.threshold(image, 0, 255, cv2.THRESH_OTSU)[1]
            image = cv2.copyMakeBorder(image, 5, 5, 5, 5, cv2.BORDER_CONSTANT, value=[250])

            captcha = pytesseract.image_to_string(
                image,
                config='--psm 13 -c tessedit_char_whitelist=ABCDEFGHIJKLMNPQRSTUVWYZ'
            )
            text = re.sub(r'[\W_]+', '', captcha).strip()
            logger.info(f"Tesseract read: '{text}'")
            return text if len(text) >= 2 else None
        except Exception as e:
            logger.warning(f"Tesseract solver error: {e}")
            return None

    def _solve_captcha(self):
        captcha_img = self._find_captcha_image()
        if not captcha_img:
            self.driver.save_screenshot("vfs_captcha_not_found.png")
            with open("vfs_page_source.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            logger.error("CAPTCHA image not found – aborting.")
            return None

        text = self._solve_captcha_2captcha(captcha_img)
        if text:
            return text

        text = self._solve_captcha_tesseract(captcha_img)
        if text:
            return text

        logger.error("All CAPTCHA solving methods failed.")
        return None

    def _wait_for_field(self, selector, timeout=MAX_WAIT, refresh_on_timeout=True):
        """Wait for a field to appear; if timeout and refresh_on_timeout, refresh and re-try."""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(selector)
            )
        except Exception as e:
            logger.warning(f"Timeout waiting for {selector}: {e}")
            if refresh_on_timeout:
                logger.info("Refreshing page and retrying CAPTCHA...")
                self.driver.refresh()
                time.sleep(5)
                try:
                    self.driver.uc_gui_click_captcha()
                except:
                    pass
                time.sleep(5)
                return WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located(selector)
                )
            else:
                raise

    def _force_set_password(self, password_field):
        """Force-set the password by cloning and replacing the element."""
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
            logger.info("No VFS credentials; skipping login.")
            return False

        logger.info(f"VFS login URL: {self.driver.current_url}")

        # 1. Email
        email_field = self._wait_for_field(self.USERNAME_SELECTOR)
        email_field.clear()
        email_field.send_keys(self.username)
        time.sleep(1)

        # 2. Password – use aggressive force-set
        password_field = self.driver.find_element(*self.PASSWORD_SELECTOR)
        password_field.click()
        time.sleep(0.5)
        self._force_set_password(password_field)
        # Re-locate the element (since it was replaced)
        password_field = self.driver.find_element(*self.PASSWORD_SELECTOR)
        # Verify and re-set if needed
        current_value = password_field.get_attribute('value')
        if current_value != self.password:
            self.driver.execute_script("arguments[0].value = arguments[1];", password_field, self.password)
        time.sleep(1)

        # 3. CAPTCHA – retry up to 3 times
        captcha_text = None
        for attempt in range(3):
            captcha_text = self._solve_captcha()
            if captcha_text:
                break
            logger.warning(f"CAPTCHA attempt {attempt+1} failed, refreshing and retrying...")
            try:
                self.driver.refresh()
                time.sleep(3)
                # After refresh, re-set password (as before)
                password_field = self.driver.find_element(*self.PASSWORD_SELECTOR)
                self._force_set_password(password_field)
            except:
                pass
            time.sleep(2)
        else:
            logger.error("All CAPTCHA attempts failed.")
            return False

        # Fill CAPTCHA
        captcha_input = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located(self.CAPTCHA_INPUT_SELECTOR)
        )
        captcha_input.clear()
        captcha_input.send_keys(captcha_text)
        time.sleep(1)
        logger.info("CAPTCHA filled.")

        # Re-set password one last time before submission
        password_field = self.driver.find_element(*self.PASSWORD_SELECTOR)
        self.driver.execute_script("arguments[0].value = arguments[1];", password_field, self.password)
        time.sleep(0.5)

        # 4. Submit
        try:
            login_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(self.LOGIN_BUTTON_SELECTOR)
            )
            login_btn.click()
            logger.info("Continue button clicked.")
        except Exception as e:
            logger.warning(f"Button click failed: {e}. Trying JavaScript submit.")
            try:
                form = self.driver.find_element(By.TAG_NAME, "form")
                self.driver.execute_script("arguments[0].submit();", form)
            except:
                return False

        time.sleep(5)

        # 5. Check login outcome
        page_source = self.driver.page_source
        if self.LOGIN_SUCCESS_INDICATOR in page_source:
            logger.info("Login successful!")
            return True
        elif "Your account has been locked" in page_source:
            logger.warning("Account locked. Wait 2 minutes.")
            time.sleep(120)
            return False
        elif "The verification words are incorrect" in page_source:
            logger.warning("Incorrect CAPTCHA. Will retry.")
            return False
        elif "rate limited" in page_source.lower():
            logger.warning("Rate limited. Wait 5 minutes.")
            time.sleep(300)
            return False
        else:
            logger.warning("Unknown login error. Check screenshot.")
            self.driver.save_screenshot("vfs_login_fail.png")
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
                logger.info("Potential slots available (no 'no open seats' message).")
                return True
        except Exception as e:
            logger.error(f"Error checking slots: {e}")
            return False