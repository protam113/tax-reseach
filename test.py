"""
collect_captcha.py - Tự động chụp ảnh CAPTCHA thật từ trang web
Chạy script này để thu thập ~500-1000 ảnh thật, sau đó label và train lại

Usage:
    python collect_captcha.py --n 500
"""

import time, os, argparse
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE = "https://tracuunnt.gdt.gov.vn"
OUT  = "captcha_real"


def collect(n: int, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    existing = len([f for f in os.listdir(out_dir) if f.endswith('.png')])
    print(f"Collecting {n} ảnh thật → {out_dir}/ (đã có {existing})")

    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(options=options)

    count = existing
    try:
        while count < n:
            try:
                driver.get(f"{BASE}/tcnnt/mstcn.jsp")
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "img[src*='captcha']"))
                )
                time.sleep(0.5)

                captcha_img = driver.find_element(By.CSS_SELECTOR, "img[src*='captcha']")
                img_bytes   = captcha_img.screenshot_as_png

                fname = f"{out_dir}/{count:05d}.png"
                with open(fname, 'wb') as f:
                    f.write(img_bytes)

                count += 1
                if count % 50 == 0:
                    print(f"  {count}/{n} collected...")

                time.sleep(0.3)  # nhẹ nhàng với server

            except Exception as e:
                print(f"  Lỗi: {e}, thử lại...")
                time.sleep(2)

    finally:
        driver.quit()

    print(f"\nDone! {count} ảnh → {out_dir}/")
    print(f"Tiếp theo: label ảnh bằng python label_tool.py")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--n',   type=int, default=500)
    parser.add_argument('--out', type=str, default=OUT)
    args = parser.parse_args()
    collect(args.n, args.out)