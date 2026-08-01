#!/usr/bin/env python3
"""
Manual test script to check slot availability without running the Telegram bot.
Usage: python text_check.py [vfs|tls|bls]
If no argument provided, checks all configured scrapers.
"""
import sys
import logging
from config import Config
from scrapers import VFSScraper, TLSScraper, BLSScraper

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
    scrapers = []
    # Determine which scrapers to run based on args
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "vfs" and Config.VFS_URL:
            scrapers.append(VFSScraper(
                username=Config.VFS_USERNAME,
                password=Config.VFS_PASSWORD,
                url=Config.VFS_URL,
                appointment_url=Config.VFS_APPOINTMENT_URL,
                headless=Config.HEADLESS  # set True via HEADLESS=true in .env
            ))
        elif arg == "tls" and Config.TLS_URL:
            scrapers.append(TLSScraper(
                username=Config.TLS_USERNAME,
                password=Config.TLS_PASSWORD,
                url=Config.TLS_URL,
                headless=False
            ))
        elif arg == "bls" and Config.BLS_URL:
            scrapers.append(BLSScraper(
                username=Config.BLS_USERNAME,
                password=Config.BLS_PASSWORD,
                url=Config.BLS_URL,
                headless=False
            ))
        else:
            print(f"Unknown or unconfigured provider: {arg}")
            sys.exit(1)
    else:
        # Check all configured
        if Config.VFS_URL:
            scrapers.append(VFSScraper(
                username=Config.VFS_USERNAME,
                password=Config.VFS_PASSWORD,
                url=Config.VFS_URL,
                appointment_url=Config.VFS_APPOINTMENT_URL,
                headless=Config.HEADLESS
            ))
        if Config.TLS_URL:
            scrapers.append(TLSScraper(
                username=Config.TLS_USERNAME,
                password=Config.TLS_PASSWORD,
                url=Config.TLS_URL,
                headless=False
            ))
        if Config.BLS_URL:
            scrapers.append(BLSScraper(
                username=Config.BLS_USERNAME,
                password=Config.BLS_PASSWORD,
                url=Config.BLS_URL,
                headless=False
            ))

    if not scrapers:
        print("No scrapers configured. Please set at least one URL in .env")
        sys.exit(1)

    for scraper in scrapers:
        check_scraper(scraper)

if __name__ == "__main__":
    main()