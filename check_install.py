#!/usr/bin/env python3
"""
Check if all dependencies are installed
"""

import sys

print("Kiểm tra cài đặt...\n")

# Check core dependencies
deps = {
    'requests': 'requests',
    'beautifulsoup4': 'bs4',
    'pandas': 'pandas',
    'openpyxl': 'openpyxl',
    'selenium': 'selenium',
}

missing = []
for name, import_name in deps.items():
    try:
        __import__(import_name)
        print(f"✅ {name}")
    except ImportError:
        print(f"❌ {name} - Run: pip install {name}")
        missing.append(name)

# Check tkinter (for GUI)
print("\nSystem dependencies:")
try:
    import tkinter
    print(f"✅ tkinter (GUI support)")
except ImportError:
    print(f"❌ tkinter - GUI will not work")
    print(f"   Install: sudo apt-get install python3-tk (Linux)")
    print(f"   Install: brew install python-tk (macOS)")

# Check ChromeDriver
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    
    driver = webdriver.Chrome(options=options)
    driver.quit()
    print("✅ ChromeDriver (Selenium support)")
except Exception as e:
    print(f"❌ ChromeDriver - {str(e)[:100]}")
    print("   Install: sudo apt-get install chromium-chromedriver (Linux)")
    print("   Or download from: https://chromedriver.chromium.org/downloads")

if missing:
    print(f"\n❌ Missing Python packages: {', '.join(missing)}")
    print(f"Run: pip install {' '.join(missing)}")
    sys.exit(1)
else:
    print(f"\n✅ All Python packages installed!")
    print(f"\nBạn có thể chạy:")
    print(f"  - GUI: python gui_app.py")
    print(f"\nLưu ý: GUI sẽ mở Chrome browser để bypass Cloudflare")
