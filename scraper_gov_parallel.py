"""
scraper_gov_parallel.py - Parallel scraping cho Cục Thuế
Chạy nhiều browser instances song song để tăng tốc
"""

import time
import random
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from pathlib import Path
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


class WorkerBrowser:
    """Một browser worker để xử lý tra cứu"""
    
    def __init__(self, worker_id: int, headless: bool = True):
        self.worker_id = worker_id
        self.headless = headless
        self.driver = None
        
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
        
        # Mỗi worker có port riêng để tránh conflict
        debug_port = 9222 + self.worker_id
        options.add_argument(f'--remote-debugging-port={debug_port}')
        
        # Mỗi worker có user-data-dir riêng
        from pathlib import Path
        profile_dir = Path(f"browser_profiles/worker_{self.worker_id}")
        profile_dir.mkdir(parents=True, exist_ok=True)
        options.add_argument(f'--user-data-dir={profile_dir.absolute()}')
        
        # Random user agent
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
        ]
        options.add_argument(f'user-agent={user_agents[self.worker_id % len(user_agents)]}')
        
        # Tạo browser instance riêng cho worker này
        self.driver = webdriver.Chrome(options=options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        print(f"  ✓ Worker {self.worker_id} sẵn sàng (Browser riêng, port {debug_port})")
        
    def close(self):
        """Đóng browser"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
    
    def refresh_tab(self):
        """Đóng tab cũ và mở tab mới"""
        try:
            if not self.driver:
                return
            
            handles = self.driver.window_handles
            self.driver.execute_script("window.open('about:blank', '_blank');")
            time.sleep(0.5)
            
            new_handles = self.driver.window_handles
            new_tab = None
            for handle in new_handles:
                if handle not in handles:
                    new_tab = handle
                    break
            
            for old_handle in handles:
                try:
                    self.driver.switch_to.window(old_handle)
                    self.driver.close()
                except:
                    pass
            
            if new_tab:
                self.driver.switch_to.window(new_tab)
            else:
                remaining = self.driver.window_handles
                if remaining:
                    self.driver.switch_to.window(remaining[-1])
            
            time.sleep(0.3)
            
        except Exception as e:
            print(f"[Worker {self.worker_id}] ⚠️ Lỗi refresh tab: {e}")
    
    def _solve_captcha(self, max_retries=3):
        """Giải CAPTCHA bằng EasyOCR"""
        for attempt in range(max_retries):
            try:
                time.sleep(1)
                captcha_img = self.driver.find_element(By.CSS_SELECTOR, "img[src*='captcha.png']")
                captcha_bytes = captcha_img.screenshot_as_png
                captcha_text = read_captcha_from_bytes(captcha_bytes)
                
                if captcha_text and len(captcha_text) == 5:
                    return captcha_text
                
                if attempt < max_retries - 1:
                    time.sleep(1)
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                    
        return None
    
    def lookup_one(self, mst: str, ho_ten: str = "", dia_chi: str = "") -> TaxRecord:
        """Tra cứu 1 MST"""
        record = TaxRecord(mst=mst, ho_ten_input=ho_ten)
        q = mst.strip()
        
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                url = f"{BASE}/tcnnt/mstcn.jsp"
                self.driver.get(url)
                
                # Đợi form load xong
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.NAME, "mst"))
                )
                
                # Đợi thêm để đảm bảo form hoàn toàn sẵn sàng
                time.sleep(2)
                
                # Nhập MST với verification
                mst_input = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.NAME, "mst"))
                )
                mst_input.clear()
                time.sleep(0.3)
                
                # Nhập từng ký tự và verify
                for char in q:
                    mst_input.send_keys(char)
                    time.sleep(random.uniform(0.15, 0.25))
                
                # Verify MST đã nhập đúng
                time.sleep(0.5)
                entered_mst = mst_input.get_attribute('value')
                if entered_mst != q:
                    print(f"[Worker {self.worker_id}] ⚠️ MST nhập sai: '{entered_mst}' != '{q}', retry...")
                    if attempt < max_attempts - 1:
                        time.sleep(2)
                        continue
                    record.loi = f"Không thể nhập MST đúng"
                    break
                
                # Nhập họ tên với verification
                if ho_ten:
                    try:
                        time.sleep(0.5)
                        fullname_input = WebDriverWait(self.driver, 5).until(
                            EC.element_to_be_clickable((By.NAME, "fullname"))
                        )
                        fullname_input.clear()
                        time.sleep(0.3)
                        for char in ho_ten:
                            fullname_input.send_keys(char)
                            time.sleep(random.uniform(0.08, 0.15))
                        time.sleep(0.3)
                    except:
                        pass
                
                # Nhập địa chỉ với verification
                if dia_chi:
                    try:
                        time.sleep(0.5)
                        address_input = WebDriverWait(self.driver, 5).until(
                            EC.element_to_be_clickable((By.NAME, "address"))
                        )
                        address_input.clear()
                        time.sleep(0.3)
                        for char in dia_chi:
                            address_input.send_keys(char)
                            time.sleep(random.uniform(0.08, 0.15))
                        time.sleep(0.3)
                    except:
                        pass
                
                # Giải CAPTCHA
                captcha_text = self._solve_captcha()
                
                if not captcha_text or len(captcha_text) != 5:
                    if attempt < max_attempts - 1:
                        time.sleep(3)
                        continue
                    record.loi = "Không thể giải CAPTCHA"
                    try:
                        record.url = self.driver.current_url
                    except:
                        record.url = ""
                    break
                
                # Nhập CAPTCHA với verification
                captcha_input = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "captcha"))
                )
                captcha_input.clear()
                time.sleep(0.5)
                
                for char in captcha_text:
                    captcha_input.send_keys(char)
                    time.sleep(random.uniform(0.2, 0.4))
                
                # Verify CAPTCHA đã nhập đúng
                time.sleep(0.5)
                entered_captcha = captcha_input.get_attribute('value')
                if entered_captcha != captcha_text:
                    print(f"[Worker {self.worker_id}] ⚠️ CAPTCHA nhập sai: '{entered_captcha}' != '{captcha_text}', retry...")
                    if attempt < max_attempts - 1:
                        time.sleep(2)
                        continue
                    record.loi = f"Không thể nhập CAPTCHA đúng"
                    break
                
                # Đợi trước khi submit
                time.sleep(random.uniform(0.8, 1.5))
                
                # Submit với explicit wait
                search_btn = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "input.subBtn"))
                )
                search_btn.click()
                
                time.sleep(3)
                
                # Lấy URL ngay sau khi submit
                try:
                    current_url = self.driver.current_url
                except:
                    current_url = ""
                
                # Parse kết quả
                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                result_table = soup.find("table", class_="ta_border")
                
                if not result_table:
                    if attempt < max_attempts - 1:
                        time.sleep(5)
                        continue
                    record.loi = "Không tìm thấy kết quả"
                    record.url = current_url
                    break
                
                rows = result_table.find_all("tr")
                if len(rows) < 2:
                    record.loi = "Không có dữ liệu"
                    record.url = current_url
                    break
                
                data_row = rows[1]
                cells = data_row.find_all("td")
                
                if len(cells) >= 5:
                    record.mst_result = cells[1].get_text(strip=True)
                    record.ten_nnt = cells[2].get_text(strip=True)
                    record.co_quan_thue = cells[3].get_text(strip=True)
                    record.trang_thai = cells[4].get_text(strip=True)
                    record.url = current_url
                    break
                else:
                    record.loi = "Cấu trúc bảng không đúng"
                    record.url = current_url
                    break
                    
            except Exception as e:
                error_msg = str(e)[:200]
                
                if attempt < max_attempts - 1:
                    time.sleep(5)
                    continue
                    
                record.loi = error_msg
                try:
                    record.url = self.driver.current_url
                except:
                    record.url = ""
                break
        
        # Đóng tab cũ và mở tab mới sau mỗi lần tra cứu
        self.refresh_tab()
        
        return record


class ParallelTaxGovScraper:
    """Quản lý nhiều browser workers"""
    
    def __init__(self, num_workers: int = 3, headless: bool = True, progress_callback=None):
        self.num_workers = num_workers
        self.headless = headless
        self.workers = []
        self.print_lock = Lock()
        self.progress_callback = progress_callback  # Callback để update progress
        self.completed_count = 0  # Đếm số item đã hoàn thành
        self.total_count = 0  # Tổng số items
        
    def __enter__(self):
        self.start()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        
    def start(self):
        """Khởi động tất cả workers"""
        print(f"🚀 Khởi động {self.num_workers} browser workers cho Cục Thuế...")
        
        for i in range(self.num_workers):
            worker = WorkerBrowser(worker_id=i+1, headless=self.headless)
            worker.start()
            self.workers.append(worker)
            # Delay nhỏ giữa các worker để tránh conflict
            if i < self.num_workers - 1:
                time.sleep(random.uniform(1.0, 2.0))
        print()
        
    def close(self):
        """Đóng tất cả workers"""
        print("\n🔒 Đóng tất cả browsers...")
        for worker in self.workers:
            worker.close()
        self.workers = []
        print("✅ Đã đóng tất cả browsers")
        
    def _process_item(self, worker: WorkerBrowser, item: dict, index: int, total: int) -> TaxRecord:
        """Xử lý 1 item với worker cụ thể"""
        mst = str(item.get("mst", "")).strip()
        if not mst:
            return TaxRecord(mst="", loi="MST trống")
        
        with self.print_lock:
            print(f"[Worker {worker.worker_id}] [{index}/{total}] Tra cứu: {mst}")
        
        ho_ten = str(item.get("ho_ten", "") or "")
        dia_chi = str(item.get("address", "") or "")
        
        result = worker.lookup_one(mst=mst, ho_ten=ho_ten, dia_chi=dia_chi)
        
        with self.print_lock:
            if result.loi:
                print(f"[Worker {worker.worker_id}]   ❌ {result.loi}")
            else:
                print(f"[Worker {worker.worker_id}]   ✅ {result.ten_nnt}")
            
            # Update completed count và gọi callback
            self.completed_count += 1
            if self.progress_callback:
                self.progress_callback(self.completed_count, self.total_count, result)
        
        # Delay dài hơn giữa các request để tránh rate limit
        # Với parallel, mỗi worker nên đợi 4-6 giây
        time.sleep(random.uniform(4.0, 6.0))
        
        return result
    
    def lookup_batch(self, records_input: list[dict]) -> list[TaxRecord]:
        """Tra cứu hàng loạt với parallel processing"""
        total = len(records_input)
        if total == 0:
            return []
        
        self.total_count = total
        self.completed_count = 0
        
        print(f"🔍 Bắt đầu tra cứu {total} MST với {self.num_workers} workers...\n")
        
        results = [None] * total
        
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            future_to_index = {}
            
            # Submit tasks với staggered start để tránh tất cả workers cùng request một lúc
            for i, item in enumerate(records_input):
                worker = self.workers[i % self.num_workers]
                
                # Delay nhỏ giữa các submission để stagger requests
                if i > 0 and i % self.num_workers == 0:
                    time.sleep(random.uniform(0.5, 1.5))
                
                future = executor.submit(self._process_item, worker, item, i+1, total)
                future_to_index[future] = i
            
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result = future.result()
                    results[index] = result
                except Exception as e:
                    mst = str(records_input[index].get("mst", ""))
                    results[index] = TaxRecord(mst=mst, loi=f"Exception: {str(e)[:100]}")
        
        return results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        mst = sys.argv[1]
        with ParallelTaxGovScraper(num_workers=1, headless=False) as scraper:
            r = scraper.lookup_batch([{"mst": mst}])[0]
            print(f"\nInput:        {r.mst}")
            print(f"Tên NNT:      {r.ten_nnt}")
            print(f"MST:          {r.mst_result}")
            print(f"CQ Thuế:      {r.co_quan_thue}")
            print(f"Trạng thái:   {r.trang_thai}")
            if r.loi:
                print(f"Lỗi:          {r.loi}")
