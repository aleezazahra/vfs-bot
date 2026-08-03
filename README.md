# VFS Visa Slot Checker

A desktop app that watches the **VFS Global** booking site and alerts you the
moment an appointment slot opens up.

No more refreshing the page every few minutes — fill in your details once, press
**Start Monitoring**, and get a pop-up the second a slot becomes available.

---

## Features

- **VFS Global only** — the app is built around the VFS EOI flow: log in, create an
  application, then check every country/centre in the dropdown for slots.
- **Your own link** — enter the exact login link for the account you created
  (not hard-coded to a single country/centre).
- **Checks all dropdown options** — every country/centre in the dropdown is
  checked and the report lists each one's slot status.
- **One-off check** (`Check Now`) and **continuous monitoring** (`Start Monitoring`)
  with a configurable check interval.
- **Instant alert** — a pop-up window appears when slots are found.
- **Session persistence** — your login session (cookies) is saved to disk, so you
  only have to complete login (including the email **OTP**) **once**.
- **CAPTCHA handling** — uses a 2Captcha API key if you provide one, otherwise falls
  back to local OCR.
- **Headless mode** — run silently in the background without a browser window.
- **Settings remembered** — credentials, links and options are stored in
  `gui_config.json`, so you don't re-enter them every time.
- **Live log + status bar** showing every step (Cloudflare bypass, CAPTCHA, login,
  dropdown selections, slot report).

---

## Requirements

- Python 3.9+
- Google Chrome (or Chromium) installed
- `tesseract-ocr` for local VFS CAPTCHA OCR (recommended)

### Install on Debian / Ubuntu

```bash
sudo apt update
sudo apt install python3 python3-pip python3-tk tesseract-ocr google-chrome-stable
pip install -r requirements.txt
```

### Install on Windows / macOS

1. Install [Python](https://www.python.org/downloads/) and
   [Google Chrome](https://www.google.com/chrome/).
2. Install Tesseract from <https://github.com/tesseract-ocr/tesseract>
   (Windows: run the installer; macOS: `brew install tesseract`).
3. Open a terminal in this folder and run:

```bash
pip install -r requirements.txt
```

> `requirements.txt`:
> `seleniumbase`, `selenium`, `webdriver-manager`, `python-dotenv`,
> `pytesseract`, `Pillow`, `opencv-python`, `numpy`

---

## Quick Start

```bash
python main.py
```

That's it — the app window opens.

---

## Step-by-step usage

### 1. Enter the VFS login link

Paste the **Login link** for the account you created, e.g.
`https://visa.vfsglobal.com/usa/en/eoi/login`.

> The link must be the actual login page of **your** account/country, because that
> is what the scraper opens and logs into.

### 2. Optional fields

- **Appointment link** — the direct booking page, e.g.
  `https://visa.vfsglobal.com/usa/en/eoi/`. If left empty the app tries to find the
  booking page automatically after login (by clicking the orange
  **Create Application** button).
- **Centre filter** — only check a specific centre/country (e.g. `Pakistan`). Leave
  empty to check **all** of them.

### 3. Enter your credentials

Fill in the **Email / username** and **Password** for that account.

> These are only stored locally in `gui_config.json`. Don't share the file.

### 4. Set the check interval

**Check every (seconds)** controls how often monitoring re-checks the site.
A sensible value is `300` (every 5 minutes). The minimum is 5 seconds.

### 5. Optional: run headless

Tick **Run headless** to hide the browser window during checks. Leave it off the
first time so you can complete login/OTP.

### 6. Start

- **Check Now** — runs a single check and shows the result in the log.
- **Start Monitoring** — checks repeatedly on the interval and **pops up an alert**
  when slots are available.
- **Stop** — stops the monitoring loop.
- **Save** — saves the current settings to `gui_config.json`.

When slots are found you'll see something like:

```
[VFS] Slot report:
  • Pakistan: 2 applicant(s): 14-08-2026
  • India: No slots available
  • Nigeria: No slots available
[VFS] ✅ Slots AVAILABLE!
```

...and an alert pop-up appears.

---

## First-time login and the email OTP

VFS sometimes sends a one-time password (OTP) to your email after sign-in.

- Keep **Run headless** **unchecked** on the first run.
- When the OTP page appears, the log says:
  `OTP verification required. Enter the code in the browser window`.
- Type the code into the open Chrome window.
- After you're logged in, the app **saves the session** to `profiles/`.
- On later runs the app reuses that session and skips login + OTP entirely.

> If the saved session expires (VFS usually keeps you logged in for a while), run
> the app once with the browser visible and complete the OTP again.

---

## How the slot checking works

1. The app opens Chrome (UC mode, which also handles Cloudflare challenges).
2. It loads your saved session, or logs in with your credentials
   (solving the CAPTCHA if needed).
3. After login it clicks the orange **Create Application** button to reach the
   appointment page, which has several dropdown menus.
4. It selects each country/centre in the dropdown turn by turn and reads the
   availability message that appears on the page (e.g.
   "Earliest available slot for 2 applicant(s) is: 14-08-2026" or
   "No open seats available").
5. The result is logged, and if any slots exist, a pop-up alert fires.
6. The session is saved again so the next check is fast.

All checks run in a background thread, so the interface stays responsive.

---

## Files

| File | Purpose |
| --- | --- |
| `main.py` | Launches the GUI. |
| `gui.py` | The desktop app (tkinter). |
| `scrapers/` | The VFS scraper (`vfs.py`) + shared base (`base.py`). |
| `config.py` | Loads `.env` values used by the scraper. |
| `text_check.py` | CLI testing tool (see below). |
| `gui_config.json` | Your settings (created on first save). |
| `profiles/` | Saved login sessions (cookies). |
| `.env` | Optional CAPTCHA key + defaults for CLI testing. |

---

## CLI testing (optional)

You can test the scraper from the terminal without opening the GUI.
Credentials/links come from `.env`.

```bash
python text_check.py
```

---

## Configuration

### `.env`

```bash
# Optional: 2Captcha API key to solve the VFS image CAPTCHA reliably.
CAPTCHA_API_KEY=

# Where login sessions are stored.
PROFILE_DIR=profiles

# Defaults for text_check.py CLI testing.
VFS_USERNAME=...
VFS_PASSWORD=...
VFS_URL=...
VFS_APPOINTMENT_URL=

# Headless mode for CLI tests.
HEADLESS=false
```

### `gui_config.json`

Created automatically when you press **Save**. Stores: login link, appointment
link, centre filter, username, password, check interval and headless flag.

---

## Troubleshooting

- **Chrome crashes / "invalid session id"** — update Chrome and rerun
  `pip install -r requirements.txt`. If you're in a container or running as root,
  you may need to launch with `--no-sandbox`.
- **Login link required** — the app refuses to run without a login link.
- **CAPTCHA can't be solved** — set a `CAPTCHA_API_KEY` (2Captcha) in `.env`;
  local OCR works but is less reliable.
- **OTP keeps appearing every run** — the saved session may have expired.
  Run once with the browser visible, enter the OTP, and it will be saved again.
- **"No dropdown menus found"** — run once (not headless) and check the log: it now
  prints every dropdown found with its options. If none are printed, the page
  layout changed — grab the saved `vfs_slot_page.html` / `vfs_slot_check_fail.png`
  from the project folder and check the dropdown structure.

---

## Security note

- Passwords are stored in plain text in `gui_config.json` and saved sessions in
  `profiles/`. Keep your computer and these files private; don't commit
  `gui_config.json`, `.env` or `profiles/` to any repository (they are already
  git-ignored).

---

*Built for personal use — scraping public booking sites can violate their terms of
service. Use responsibly and at your own risk.*
