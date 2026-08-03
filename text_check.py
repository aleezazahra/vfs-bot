#!/usr/bin/env python3
"""
Manual test script to check VFS slot availability without running the GUI.
Usage: python text_check.py
"""
import sys
import logging
from config import Config
from scrapers import VFSScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def check_scraper(scraper):
    print(f"\n--- Checking {scraper.__class__.__name__} ---")
    available, msg = scraper.run_check()
    print(msg)
    if available:
        print("✅ SLOTS AVAILABLE!")
    else:
        print("❌ No slots available.")
    print("--- Done ---\n")

def main():
    if not Config.VFS_URL:
        print("No VFS_URL configured. Set it in .env first.")
        sys.exit(1)

    scraper = VFSScraper(
        username=Config.VFS_USERNAME,
        password=Config.VFS_PASSWORD,
        url=Config.VFS_URL,
        appointment_url=Config.VFS_APPOINTMENT_URL,
        headless=Config.HEADLESS,
    )
    check_scraper(scraper)

if __name__ == "__main__":
    main()
