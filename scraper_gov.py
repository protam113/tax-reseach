"""
scraper_gov.py - Scraper cho tracuunnt.gdt.gov.vn (Cục Thuế)
Cần giải CAPTCHA bằng EasyOCR
"""

import time
import random
from dataclasses import dataclass
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from scan_code import read_captcha_from_bytes

BASE = "https://tracuunnt.gdt.gov.vn"


@dataclass
class TaxRecord:
    mst: str
    ho_ten_input: str = ""
    ten_nnt: str = ""
    mst_result: str = ""
    dia_chi_result: str = ""
    co_quan_thue: str = ""
    trang_thai: str = ""
    loi: str = ""
    url: str = ""


class TaxGovScraper:
    def __init__(self, headless=True):
        self.headless = headless
        self.driver = None
        self.error_count = 0  # Đếm số lần lỗi liên tiếp
        self.max_errors_before_refresh = 2  # Số lỗi tối đa trước khi refresh
        self.lookup_count = 0  # Đếm số lần tra cứu
        self.refresh_after_lookups = 5  # Refresh sau mỗi 5 lần tra cứu (CAPTCHA dễ lỗi)
        
    def __enter__(self):
        self.start()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        
    def start(self):
        """Khởi động browser"""
        options = Options()
        if self.headless:
            options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        self.driver = webdriver.Chrome(options=options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
    def close(self):
        """Đóng browser"""
        if self.driver:
            self.driver.quit()
    
    def refresh_tab(self):
        """Đóng tab hiện tại hoàn toàn và mở tab mới sạch sẽ"""
        try:
            if not self.driver:
                return
            
            print(f"  [Refresh] 🔄 Đóng tab cũ và mở tab mới...")
            
            # Lấy tất cả window handles
            handles = self.driver.window_handles
            
            # Mở tab mới trước
            self.driver.execute_script("window.open('about:blank', '_blank');")
            time.sleep(0.5)
            
            # Lấy lại danh sách handles sau khi mở tab mới
            new_handles = self.driver.window_handles
            
            # Tìm tab mới (handle không có trong list cũ)
            new_tab = None
            for handle in new_handles:
                if handle not in handles:
                    new_tab = handle
                    break
            
            # Đóng tất cả tab cũ
            for old_handle in handles:
                try:
                    self.driver.switch_to.window(old_handle)
                    self.driver.close()
                except:
                    pass
            
            # Chuyển sang tab mới
            if new_tab:
                self.driver.switch_to.window(new_tab)
            else:
                # Fallback: chuyển sang handle cuối cùng
                remaining = self.driver.window_handles
                if remaining:
                    self.driver.switch_to.window(remaining[-1])
            
            # Reset counters
            self.error_count = 0
            self.lookup_count = 0
            
            time.sleep(0.5)
            print(f"  [Refresh] ✅ Tab mới đã sẵn sàng")
            
        except Exception as e:
            print(f"  [Refresh] ⚠️ Lỗi refresh tab: {e}")
            # Nếu lỗi nghiêm trọng, thử restart browser
            try:
                if not self.driver.window_handles:
                    print(f"  [Refresh] 🔄 Restart browser...")
                    self.close()
                    self.start()
            except:
                pass
    
    def should_refresh(self, had_error: bool = False) -> bool:
        """Kiểm tra xem có nên refresh tab không"""
        if had_error:
            self.error_count += 1
            if self.error_count >= self.max_errors_before_refresh:
                return True
        else:
            self.error_count = 0  # Reset error count khi thành công
        
        self.lookup_count += 1
        if self.lookup_count >= self.refresh_after_lookups:
            return True
        
        return False
    
    def _solve_captcha(self, max_retries=3, save_debug=True):
        """Giải CAPTCHA bằng EasyOCR với retry - KHÔNG refresh page"""
        import os
        from datetime import datetime
        
        # Tạo folder debug nếu chưa có
        if save_debug:
            debug_folder = "captcha_debug"
            os.makedirs(debug_folder, exist_ok=True)
        
        for attempt in range(max_retries):
            try:
                # Đợi captcha load
                time.sleep(1)
                
                # Tìm captcha image
                captcha_img = self.driver.find_element(By.CSS_SELECTOR, "img[src*='captcha.png']")
                
                # Lấy screenshot của captcha
                captcha_bytes = captcha_img.screenshot_as_png
                
                # Save ảnh để debug
                if save_debug:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"{debug_folder}/captcha_{timestamp}_attempt{attempt+1}.png"
                    with open(filename, 'wb') as f:
                        f.write(captcha_bytes)
                    print(f"  [Debug] Saved: {filename}")
                
                # Giải captcha bằng EasyOCR
                captcha_text = read_captcha_from_bytes(captcha_bytes)
                
                # Save kết quả vào text file
                if save_debug:
                    result_file = f"{debug_folder}/captcha_{timestamp}_attempt{attempt+1}_result.txt"
                    with open(result_file, 'w') as f:
                        f.write(f"Result: {captcha_text}\n")
                        f.write(f"Length: {len(captcha_text)}\n")
                
                # CAPTCHA của Cục Thuế luôn 5 ký tự
                if captcha_text and len(captcha_text) == 5:
                    print(f"  [Captcha] ✅ Đọc được: {captcha_text}")
                    return captcha_text
                
                # Nếu không đủ 5 ký tự, thử lại với cùng ảnh
                if attempt < max_retries - 1:
                    print(f"  [Captcha] ⚠️ Chỉ đọc được {len(captcha_text)} ký tự, thử đọc lại...")
                    time.sleep(1)
                    # Không refresh, chỉ thử đọc lại
                    
            except Exception as e:
                print(f"  [Captcha] Lỗi: {str(e)[:100]}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                    
        return None
            
    def lookup_one(self, mst: str, ho_ten: str = "", dia_chi: str = "") -> TaxRecord:
        """Tra cứu 1 MST trên tracuunnt.gdt.gov.vn"""
        record = TaxRecord(mst=mst, ho_ten_input=ho_ten)
        q = mst.strip()
        had_error = False
        
        max_attempts = 3  # Retry nếu CAPTCHA sai hoặc rate limit
        
        for attempt in range(max_attempts):
            try:
                # Load trang tra cứu
                url = f"{BASE}/tcnnt/mstcn.jsp"
                self.driver.get(url)
                
                # Đợi form load
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.NAME, "mst"))
                )
                
                # Delay để tránh rate limit
                time.sleep(2)
                
                # Nhập MST từng ký tự như người thật
                mst_input = self.driver.find_element(By.NAME, "mst")
                mst_input.clear()
                for char in q:
                    mst_input.send_keys(char)
                    time.sleep(random.uniform(0.1, 0.3))
                
                # Nhập họ tên nếu có
                if ho_ten:
                    try:
                        time.sleep(0.5)
                        fullname_input = self.driver.find_element(By.NAME, "fullname")
                        fullname_input.clear()
                        for char in ho_ten:
                            fullname_input.send_keys(char)
                            time.sleep(random.uniform(0.05, 0.15))
                    except:
                        pass
                
                # Nhập địa chỉ nếu có
                if dia_chi:
                    try:
                        time.sleep(0.5)
                        address_input = self.driver.find_element(By.NAME, "address")
                        address_input.clear()
                        for char in dia_chi:
                            address_input.send_keys(char)
                            time.sleep(random.uniform(0.05, 0.15))
                    except:
                        pass
                
                # Giải CAPTCHA
                print(f"  [Captcha] Đang giải CAPTCHA (lần {attempt + 1}/{max_attempts})...")
                captcha_text = self._solve_captcha()
                
                if not captcha_text or len(captcha_text) != 5:
                    had_error = True
                    if attempt < max_attempts - 1:
                        print(f"  [Retry] Không giải được CAPTCHA đúng, reload page và thử lại...")
                        time.sleep(3)
                        continue  # Reload page ở đầu loop
                    record.loi = "Không thể giải CAPTCHA sau nhiều lần thử"
                    record.url = self.driver.current_url
                    break
                
                # Verify MST vẫn còn trong form
                try:
                    mst_check = self.driver.find_element(By.NAME, "mst")
                    current_mst = mst_check.get_attribute('value')
                    if current_mst != q:
                        print(f"  [Warning] MST bị mất, nhập lại...")
                        mst_check.clear()
                        for char in q:
                            mst_check.send_keys(char)
                            time.sleep(random.uniform(0.1, 0.3))
                except:
                    pass
                
                # Nhập CAPTCHA từng ký tự như người thật
                captcha_input = self.driver.find_element(By.ID, "captcha")
                captcha_input.clear()
                time.sleep(0.5)
                for char in captcha_text:
                    captcha_input.send_keys(char)
                    time.sleep(random.uniform(0.15, 0.35))
                
                # Delay trước khi click submit
                time.sleep(random.uniform(0.5, 1.0))
                
                # Submit form
                search_btn = self.driver.find_element(By.CSS_SELECTOR, "input.subBtn")
                search_btn.click()
                
                # Đợi kết quả
                time.sleep(3)
                
                # Parse kết quả
                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                
                # Tìm bảng kết quả
                result_table = soup.find("table", class_="ta_border")
                
                if not result_table:
                    # Có thể CAPTCHA sai, thử lại
                    had_error = True
                    if attempt < max_attempts - 1:
                        print(f"  [Retry] Không tìm thấy kết quả (CAPTCHA có thể sai), thử lại...")
                        time.sleep(5)  # Delay lâu hơn trước khi retry
                        continue
                    record.loi = "Không tìm thấy kết quả sau nhiều lần thử"
                    record.url = self.driver.current_url
                    break
                
                # Parse dòng đầu tiên trong bảng
                rows = result_table.find_all("tr")
                if len(rows) < 2:  # Header + ít nhất 1 dòng data
                    record.loi = "Không có dữ liệu"
                    record.url = self.driver.current_url
                    had_error = True
                    break
                
                # Lấy dòng đầu tiên (index 1, vì 0 là header)
                data_row = rows[1]
                cells = data_row.find_all("td")
                
                if len(cells) >= 5:
                    # STT | MST | Tên | CQ Thuế | Trạng thái
                    record.mst_result = cells[1].get_text(strip=True)
                    record.ten_nnt = cells[2].get_text(strip=True)
                    record.co_quan_thue = cells[3].get_text(strip=True)
                    record.trang_thai = cells[4].get_text(strip=True)
                    record.url = self.driver.current_url
                    print(f"  [Success] ✅ Tìm thấy: {record.ten_nnt}")
                    break  # Thành công, thoát loop
                else:
                    record.loi = "Cấu trúc bảng không đúng"
                    record.url = self.driver.current_url
                    had_error = True
                    break
                    
            except Exception as e:
                error_msg = str(e)[:200]
                print(f"  [Error] {error_msg}")
                had_error = True
                
                if attempt < max_attempts - 1:
                    print(f"  [Retry] Thử lại sau 5 giây...")
                    time.sleep(5)
                    continue
                    
                record.loi = error_msg
                try:
                    if self.driver:
                        record.url = self.driver.current_url
                except:
                    pass
                break
        
        # Đóng tab cũ và mở tab mới sau mỗi lần tra cứu (dù thành công hay lỗi)
        print(f"  [Refresh] 🔄 Đóng tab cũ và mở tab mới...")
        self.refresh_tab()

        return record
    
    def lookup_batch(self, records_input: list[dict]) -> list[TaxRecord]:
        """Tra cứu hàng loạt"""
        results = []
        total = len(records_input)
        
        for i, item in enumerate(records_input, 1):
            mst = str(item.get("mst", "")).strip()
            if not mst:
                continue
            label = "(MST)"
            print(f"\n[{i}/{total}] Tra cứu: {mst} {label}")
            
            ho_ten = str(item.get("ho_ten", "") or "")
            dia_chi = str(item.get("address", "") or "")
            
            r = self.lookup_one(mst=mst, ho_ten=ho_ten, dia_chi=dia_chi)
            results.append(r)
            
            if r.loi:
                print(f"  ❌ {r.loi}")
            else:
                print(f"  ✅ {r.ten_nnt} | MST: {r.mst_result}")
            
            # Delay dài hơn giữa các request để tránh rate limit
            if i < total:
                delay = random.uniform(8.0, 12.0)  # 8-12 giây
                print(f"  [Delay] Đợi {delay:.1f}s trước request tiếp theo...")
                time.sleep(delay)
                
        return results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        mst = sys.argv[1]
        with TaxGovScraper(headless=False) as scraper:
            r = scraper.lookup_one(mst)
            print(f"\nInput:        {r.mst}")
            print(f"Tên NNT:      {r.ten_nnt}")
            print(f"MST:          {r.mst_result}")
            print(f"Địa chỉ:      {r.dia_chi_result}")
            print(f"CQ Thuế:      {r.co_quan_thue}")
            print(f"Trạng thái:   {r.trang_thai}")
            print(f"URL:          {r.url}")
            if r.loi:
                print(f"Lỗi:          {r.loi}")
