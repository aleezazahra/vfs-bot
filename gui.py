#!/usr/bin/env python3
"""
Desktop GUI to check visa appointment slots on the VFS Global website.

Users enter the provider, the login link for the account they created, their
credentials and a check interval. The app scrapes slot availability in the
background and pops up an alert when slots are found.

No Telegram required.
"""
import json
import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

from config import Config  # noqa: F401  (loads .env for the scrapers)
from scrapers import VFSScraper

logger = logging.getLogger(__name__)

CONFIG_FILE = "gui_config.json"

PROVIDERS = {
    "VFS": {"cls": VFSScraper, "needs_appointment_url": True},
}


class QueueLogHandler(logging.Handler):
    """Forward every log record (login, captcha, cloudflare, slots, ...) to a
    thread-safe queue that the GUI polls and prints in the log panel."""

    def __init__(self, queue):
        super().__init__()
        self.queue = queue
        self.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s",
                                            datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            self.queue.put(self.format(record))
        except Exception:
            pass


class SlotCheckerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Visa Slot Checker")
        self.root.geometry("760x620")
        self.root.minsize(680, 540)

        # Form variables
        self.provider = tk.StringVar(value="VFS")
        self.url = tk.StringVar()
        self.appointment_url = tk.StringVar()
        self.centre = tk.StringVar()
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.interval = tk.StringVar(value="300")
        self.headless = tk.BooleanVar(value=False)

        # Threading / UI communication
        self.log_queue = queue.Queue()
        self.log_messages = queue.Queue()
        self.busy = threading.Lock()
        self.stop_event = threading.Event()
        self.monitor_thread = None

        # Forward all scraper logs (login, captcha, cloudflare, slots) to the GUI.
        root_logger = logging.getLogger()
        if not any(isinstance(h, QueueLogHandler) for h in root_logger.handlers):
            root_logger.setLevel(logging.INFO)
            root_logger.addHandler(QueueLogHandler(self.log_messages))

        self._build_ui()
        self._load_config()
        self._refresh_provider_fields()

        self.root.after(100, self._poll_queue)
        self.root.after(100, self._poll_logs)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        form = ttk.LabelFrame(main, text="Account details", padding=12)
        form.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Provider:").grid(row=0, column=0, sticky="w", pady=3)
        provider_box = ttk.Combobox(
            form, textvariable=self.provider, state="readonly",
            values=list(PROVIDERS.keys()), width=28,
        )
        provider_box.grid(row=0, column=1, sticky="ew", pady=3)
        provider_box.bind("<<ComboboxSelected>>", lambda e: self._refresh_provider_fields())

        ttk.Label(form, text="Login link:").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.url, width=60).grid(row=1, column=1, sticky="ew", pady=3)

        self.appointment_url_label = ttk.Label(form, text="Appointment link (optional):")
        self.appointment_url_entry = ttk.Entry(form, textvariable=self.appointment_url, width=60)
        self.centre_label = ttk.Label(form, text="Centre filter (optional):")
        self.centre_entry = ttk.Entry(form, textvariable=self.centre, width=60)

        self.appointment_url_label.grid(row=2, column=0, sticky="w", pady=3)
        self.appointment_url_entry.grid(row=2, column=1, sticky="ew", pady=3)
        self.centre_label.grid(row=3, column=0, sticky="w", pady=3)
        self.centre_entry.grid(row=3, column=1, sticky="ew", pady=3)

        ttk.Label(form, text="Email / username:").grid(row=4, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.username, width=60).grid(row=4, column=1, sticky="ew", pady=3)

        ttk.Label(form, text="Password:").grid(row=5, column=0, sticky="w", pady=3)
        pass_entry = ttk.Entry(form, textvariable=self.password, width=60, show="*")
        pass_entry.grid(row=5, column=1, sticky="ew", pady=3)

        ttk.Label(form, text="Check every (seconds):").grid(row=6, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.interval, width=60).grid(row=6, column=1, sticky="ew", pady=3)

        ttk.Checkbutton(form, text="Run headless (no browser window)", variable=self.headless)\
            .grid(row=7, column=1, sticky="w", pady=6)

        # Buttons
        btn_row = ttk.Frame(main, padding=(0, 4))
        btn_row.grid(row=2, column=0, sticky="ew")
        ttk.Button(btn_row, text="Save", command=self._save_config).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="Check Now", command=self.on_check_now).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="Start Monitoring", command=self.on_start).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="Stop", command=self.on_stop).pack(side=tk.LEFT, padx=6)

        # Log area
        log_frame = ttk.LabelFrame(main, text="Log", padding=6)
        log_frame.grid(row=1, column=0, sticky="nsew", pady=4)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=12, state=tk.DISABLED,
                                                  font=("Monospace", 9))
        self.log_text.grid(row=0, column=0, sticky="nsew")

        # Status bar
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(main, textvariable=self.status_var, anchor="w", relief=tk.SUNKEN,
                  padding=(6, 3)).grid(row=3, column=0, sticky="ew", pady=(6, 0))

    def _refresh_provider_fields(self):
        name = self.provider.get()
        needs = PROVIDERS[name]["needs_appointment_url"]
        state = "normal" if needs else "disabled"
        self.appointment_url_label.configure(state=state)
        self.appointment_url_entry.configure(state=state)
        self.centre_label.configure(state=state)
        self.centre_entry.configure(state=state)
        self._load_provider(name)

    # ------------------------------------------------------------- helpers
    def _log(self, message):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _poll_logs(self):
        try:
            while True:
                self._log(self.log_messages.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._poll_logs)

    def _poll_queue(self):
        try:
            while True:
                available, msg, provider = self.log_queue.get_nowait()
                self._log(msg)
                lower = msg.lower()
                if "login failed" in lower:
                    self.status_var.set(f"{provider}: LOGIN FAILED - check credentials.")
                elif f"[{provider.lower()}] error" in lower:
                    self.status_var.set(f"{provider}: check error - see log.")
                elif available:
                    self.status_var.set(f"{provider}: SLOTS AVAILABLE!")
                    messagebox.showinfo("Slots Available!", msg)
                else:
                    self.status_var.set(f"{provider}: no slots right now.")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _validate(self):
        if not self.url.get().strip():
            self._log("Error: login link is required.")
            return False
        if not self.username.get().strip():
            self._log("Error: email/username is required.")
            return False
        return True

    def _get_interval(self):
        try:
            return max(int(self.interval.get()), 5)
        except ValueError:
            return 300

    def _build_scraper(self):
        name = self.provider.get()
        info = PROVIDERS[name]
        kwargs = {
            "username": self.username.get().strip(),
            "password": self.password.get(),
            "url": self.url.get().strip(),
            "headless": self.headless.get(),
        }
        if info["needs_appointment_url"]:
            kwargs["appointment_url"] = self.appointment_url.get().strip() or None
            kwargs["centre"] = self.centre.get().strip() or None
        return info["cls"](**kwargs)

    # ------------------------------------------------------------ checking
    def _run_check_once(self):
        if not self.busy.acquire(blocking=False):
            self.log_queue.put((None, "Skipping: a check is already running.", self.provider.get()))
            return
        provider = self.provider.get()
        try:
            scraper = self._build_scraper()
            self._log(f"[{provider}] Checking slots ...")
            available, msg = scraper.run_check()
            self.log_queue.put((available, f"[{provider}] {msg}", provider))
        except Exception as e:
            logger.exception("Check failed")
            self.log_queue.put((None, f"[{provider}] Error: {e}", provider))
        finally:
            self.busy.release()

    def _monitor_loop(self):
        while not self.stop_event.is_set():
            self._run_check_once()
            self.stop_event.wait(self._get_interval())

    def on_check_now(self):
        if not self._validate():
            return
        self._save_config()
        threading.Thread(target=self._run_check_once, daemon=True).start()

    def on_start(self):
        if not self._validate():
            return
        self._save_config()
        if self.monitor_thread and self.monitor_thread.is_alive():
            self._log("Monitoring is already running.")
            return
        self.stop_event.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        self.status_var.set("Monitoring started.")
        self._log(f"Monitoring started (every {self._get_interval()}s).")

    def on_stop(self):
        self.stop_event.set()
        self.status_var.set("Monitoring stopped.")
        self._log("Monitoring stopped.")

    # ------------------------------------------------------------- config
    def _provider_key(self):
        return self.provider.get().lower()

    def _save_config(self):
        data = self._load_all()
        data.setdefault("providers", {})[self._provider_key()] = {
            "url": self.url.get().strip(),
            "appointment_url": self.appointment_url.get().strip(),
            "centre": self.centre.get().strip(),
            "username": self.username.get().strip(),
            "password": self.password.get(),
            "interval": self._get_interval(),
            "headless": self.headless.get(),
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)
        self._log(f"Saved settings to {CONFIG_FILE}.")

    def _load_all(self):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            return {}

    def _load_provider(self, name):
        prov = self._load_all().get("providers", {}).get(name.lower())
        if not prov:
            return
        self.url.set(prov.get("url", ""))
        self.appointment_url.set(prov.get("appointment_url", ""))
        self.centre.set(prov.get("centre", ""))
        self.username.set(prov.get("username", ""))
        self.password.set(prov.get("password", ""))
        self.interval.set(prov.get("interval", 300))
        self.headless.set(bool(prov.get("headless", False)))

    def _load_config(self):
        self._load_provider(self.provider.get())

    # -------------------------------------------------------------- close
    def _on_close(self):
        self.stop_event.set()
        self.root.destroy()


def run_app():
    root = tk.Tk()
    SlotCheckerApp(root)
    root.mainloop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    run_app()
