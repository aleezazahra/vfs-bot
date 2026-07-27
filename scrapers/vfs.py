import time
import logging
import io
import base64
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
import pytesseract
from .base import BaseScraper
from config import Config

logger = logging.getLogger(__name__)

class VFSScraper(BaseScraper):
    USERNAME_SELECTOR = (By.ID, "EmailId")
    PASSWORD_SELECTOR = (By.ID, "Password")
    CAPTCHA_INPUT_SELECTOR = (By.ID, "CaptchaInputText")
    LOGIN_BUTTON_SELECTOR = (By.CSS_SELECTOR, "input[type='submit'][value='Continue']")

    CAPTCHA_IMAGE_SELECTORS = [
        (By.XPATH, "//img[contains(@src, 'captcha')]"),
        (By.XPATH, "//img[contains(@src, 'Captcha')]"),
        (By.XPATH, "//img[contains(@src, 'challenge')]"),
        (By.XPATH, "//img[contains(@src, 'Cap')]"),
        (By.XPATH, "//img[contains(@src, 'verification')]"),
        (By.XPATH, "//img[contains(@src, 'code')]"),
        (By.XPATH, "//img[contains(@id, 'captcha')]"),
        (By.XPATH, "//img[contains(@id, 'Captcha')]"),
        (By.XPATH, "//img[contains(@class, 'captcha')]"),
        (By.XPATH, "//img[contains(@class, 'Captcha')]"),
        (By.XPATH, "//div[contains(@class, 'captcha')]//img"),
        (By.XPATH, "//form//img[contains(@src, '.png')]"),
        (By.XPATH, "//img[not(contains(@src, 'logo'))]",),
    ]

    def _find_captcha_image(self):
        for by, value in self.CAPTCHA_IMAGE_SELECTORS:
            try:
                img = WebDriverWait(self.driver, 2).until(
                    EC.presence_of_element_located((by, value))
                )
                if img.size['width'] < 30 or img.size['height'] < 30:
                    continue
                logger.info(f"✅ Captcha found with: {by}={value}")
                return img
            except Exception:
                continue
        logger.error("❌ No captcha image found with any selector.")
        return None

    def _solve_captcha_ocr(self, captcha_img):
        try:
            location = captcha_img.location
            size = captcha_img.size
            png = self.driver.get_screenshot_as_png()
            img = Image.open(io.BytesIO(png))
            left, top = location['x'], location['y']
            right = left + size['width']
            bottom = top + size['height']
            captcha_crop = img.crop((left, top, right, bottom))
            text = pytesseract.image_to_string(captcha_crop, config='--psm 8').strip()
            logger.info(f"OCR read: '{text}'")
            return text if len(text) >= 2 else None
        except Exception as e:
            logger.warning(f"OCR error: {e}")
            return None

    def _solve_captcha_2captcha(self, captcha_img):
        api_key = getattr(Config, 'CAPTCHA_API_KEY', None)
        if not api_key:
            logger.warning("No 2Captcha API key configured.")
            return None

        logger.info(f"Using 2Captcha key ending in '...{api_key[-4:]}' (len={len(api_key)}).")

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
                error_code = result.get('request')
                logger.error(f"2Captcha submit failed: {error_code}")
                if error_code == 'ERROR_KEY_DOES_NOT_EXIST':
                    logger.error(
                        "The CAPTCHA_API_KEY in your config does not match any active "
                        "2Captcha account key. Check it against your 2Captcha dashboard "
                        "(no quotes, no trailing whitespace)."
                    )
                elif error_code == 'ERROR_ZERO_BALANCE':
                    logger.error("2Captcha account balance is zero.")
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
                    logger.error(f"2Captcha poll failed: {poll_result.get('request')}")
                    return None
            logger.error("2Captcha timeout waiting for solution.")
            return None
        except Exception as e:
            logger.error(f"2Captcha exception: {e}")
            return None

    def _solve_captcha(self):
        captcha_img = self._find_captcha_image()
        if not captcha_img:
            self.driver.save_screenshot("vfs_captcha_debug.png")
            with open("vfs_page_source.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            logger.error("Captcha image not found. Saved vfs_captcha_debug.png and vfs_page_source.html")
            return None

        text = self._solve_captcha_ocr(captcha_img)
        if text:
            return text

        text = self._solve_captcha_2captcha(captcha_img)
        if text:
            return text

        logger.warning("Automatic CAPTCHA solving failed (OCR + 2Captcha). No manual fallback available in unattended mode.")
        if getattr(Config, 'ALLOW_MANUAL_CAPTCHA', False):
            try:
                print("\n" + "="*50)
                print("⚠️  Automatic CAPTCHA solving failed.")
                print("Please look at the browser window and type the text shown in the image.")
                text = input("Enter CAPTCHA text: ").strip()
                print("="*50 + "\n")
                return text or None
            except EOFError:
                logger.error("No interactive stdin available for manual CAPTCHA entry; skipping this cycle.")
                return None
        return None

    def login(self):
        if not self.username or not self.password:
            logger.info("No VFS credentials; skipping login.")
            return

        logger.info(f"VFS login URL: {self.driver.current_url}")

        try:
            email_field = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(self.USERNAME_SELECTOR)
            )
        except Exception:
            logger.warning("Email field not found. Refreshing and retrying CAPTCHA.")
            self.driver.refresh()
            time.sleep(3)
            try:
                self.driver.uc_gui_click_captcha()
            except Exception:
                pass
            time.sleep(3)
            email_field = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(self.USERNAME_SELECTOR)
            )

        email_field.clear()
        email_field.send_keys(self.username)
        time.sleep(1)

        password_field = self.driver.find_element(*self.PASSWORD_SELECTOR)
        password_field.clear()
        password_field.send_keys(self.password)
        time.sleep(1)

        captcha_text = self._solve_captcha()
        if captcha_text:
            try:
                captcha_input = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located(self.CAPTCHA_INPUT_SELECTOR)
                )
                captcha_input.clear()
                captcha_input.send_keys(captcha_text)
                time.sleep(1)
                logger.info("CAPTCHA filled.")
            except Exception as e:
                logger.error(f"CAPTCHA input field not found: {e}")
                self.driver.save_screenshot("vfs_captcha_input_error.png")
                raise
        else:
            logger.warning("No captcha text – aborting login for this cycle.")
            return

        try:
            login_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(self.LOGIN_BUTTON_SELECTOR)
            )
            login_btn.click()
            logger.info("Clicked Continue.")
        except Exception as e:
            logger.warning(f"Continue button failed: {e}")
            try:
                form = self.driver.find_element(By.TAG_NAME, "form")
                self.driver.execute_script("arguments[0].submit();", form)
                logger.info("Submitted form via JS.")
            except Exception:
                raise

        logger.info("Login submitted.")
        time.sleep(5)

    def check_slots(self):
        try:
            WebDriverWait(self.driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            page_source = self.driver.page_source.lower()
            positive = ["book appointment", "select appointment", "available slots", "slot available"]
            negative = ["no appointments", "fully booked", "no slots", "unavailable", "all booked"]
            for neg in negative:
                if neg in page_source:
                    return False
            for pos in positive:
                if pos in page_source:
                    return True
            return False
        except Exception as e:
            logger.error(f"Error checking slots: {e}")
            return False