"""
scraper_parallel.py - Parallel scraping với nhiều browser instances
Mỗi worker chạy trong 1 browser riêng với profile/tài khoản riêng
"""

import time
import random
import json
from pathlib import Path
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from queue import Queue
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup

BASE = "https://masothue.com"


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


@dataclass
class AccountConfig:
    """Cấu hình tài khoản cho mỗi worker"""
    id: int
    username: str = ""
    password: str = ""
    note: str = ""
    profile_dir: Optional[str] = None


def load_accounts() -> List[AccountConfig]:
    """Load danh sách tài khoản từ config.json"""
    config_path = Path("config.json")
    if not config_path.exists():
        return []
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    accounts = []
    for acc in config.get("accounts", []):
        accounts.append(AccountConfig(
            id=acc.get("id", 0),
            username=acc.get("username", ""),
            password=acc.get("password", ""),
            note=acc.get("note", "")
        ))
    
    return accounts


def _parse_detail_page(soup: BeautifulSoup) -> dict:
    """Parse trang chi tiết: table.table-taxinfo"""
    result = {}
    table = soup.find("table", class_="table-taxinfo")
    if not table:
        return result

    thead = table.find("thead")
    if thead:
        th = thead.find("th")
        if th:
            span = th.find("span", class_="copy")
            result["ten_nnt"] = span.get_text(strip=True) if span else th.get_text(strip=True)

    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        key = cells[0].get_text(" ", strip=True).lower()
        
        if "mã số thuế" in key:
            span = cells[1].find("span", class_="copy")
            if span:
                result["mst_result"] = span.get_text(strip=True)
            else:
                val = cells[1].get_text(" ", strip=True)
                result["mst_result"] = val.split()[0]
        elif "địa chỉ" in key:
            result["dia_chi_result"] = cells[1].get_text(" ", strip=True)
        elif "cơ quan" in key or "quản lý" in key:
            result["co_quan_thue"] = cells[1].get_text(" ", strip=True)
        elif "tình trạng" in key or "trạng thái" in key:
            a_tag = cells[1].find("a")
            if a_tag:
                result["trang_thai"] = a_tag.get_text(strip=True)
            else:
                result["trang_thai"] = cells[1].get_text(" ", strip=True)

    return result


class WorkerBrowser:
    """Một browser worker để xử lý tra cứu với profile riêng"""
    
    def __init__(self, worker_id: int, headless: bool = True, account: Optional[AccountConfig] = None, 
                 use_profile: bool = True, profiles_dir: str = "./browser_profiles"):
        self.worker_id = worker_id
        self.headless = headless
        self.account = account
        self.use_profile = use_profile
        self.profiles_dir = profiles_dir
        self.driver = None
        
    def start(self):
        """Khởi động browser với profile riêng cho mỗi worker"""
        options = Options()
        
        # Headless mode
        if self.headless:
            options.add_argument('--headless')
        
        # Sử dụng profile riêng cho mỗi worker
        if self.use_profile:
            # Tạo thư mục profiles nếu chưa có
            profile_path = Path(self.profiles_dir) / f"worker_{self.worker_id}"
            profile_path.mkdir(parents=True, exist_ok=True)
            
            options.add_argument(f'--user-data-dir={profile_path.absolute()}')
            options.add_argument(f'--profile-directory=Profile{self.worker_id}')
            
            print(f"  Worker {self.worker_id}: Sử dụng profile tại {profile_path}")
        else:
            # Incognito mode nếu không dùng profile
            options.add_argument('--incognito')
        
        # Các options khác
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # Random user agent để tránh bị phát hiện
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36',
        ]
        options.add_argument(f'user-agent={user_agents[self.worker_id % len(user_agents)]}')
        
        # Khởi tạo driver
        self.driver = webdriver.Chrome(options=options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # Hiển thị thông tin tài khoản nếu có
        if self.account:
            print(f"  Worker {self.worker_id}: Tài khoản '{self.account.note}' ({self.account.username})")
        
    def close(self):
        """Đóng browser"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            
    def lookup_one(self, mst: str, ho_ten: str = "") -> TaxRecord:
        """Tra cứu 1 MST"""
        record = TaxRecord(mst=mst, ho_ten_input=ho_ten)
        q = mst.strip()
        had_error = False
        
        try:
            # Xác định loại search
            search_type = "auto"
            if len(q) == 10:
                search_type = "personalTax"
            elif len(q) == 12:
                search_type = "identity"
            
            # Build URL
            url = f"{BASE}/Search/?q={q}&type={search_type}"
            if len(q) == 12:
                url += "&force-search=1"
            
            # Load page
            self.driver.get(url)
            
            # Đợi Cloudflare check
            time.sleep(random.uniform(1.5, 2.5))
            
            # Đợi page load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Parse HTML
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            current_url = self.driver.current_url
            is_search_page = "Search" in current_url
            
            if not is_search_page:
                # Đã redirect về trang chi tiết
                has_table = soup.find("table", class_="table-taxinfo") is not None
                if has_table:
                    info = _parse_detail_page(soup)
                    mst_in_result = info.get("mst_result", "")
                    
                    if mst_in_result == q:
                        record.ten_nnt        = info.get("ten_nnt", "")
                        record.mst_result     = mst_in_result
                        record.dia_chi_result = info.get("dia_chi_result", "")
                        record.co_quan_thue   = info.get("co_quan_thue", "")
                        record.trang_thai     = info.get("trang_thai", "")
                        record.url            = current_url
                    else:
                        record.loi = f"MST {q} không tồn tại (redirect về {mst_in_result})"
                        record.url = current_url
                        had_error = True
                else:
                    record.loi = "Không tìm thấy bảng thông tin"
                    record.url = current_url
                    had_error = True
            else:
                # Trang search - tìm trong listing
                tax_listing = soup.find("div", class_="tax-listing")
                if not tax_listing:
                    record.loi = "Không tìm thấy kết quả"
                    record.url = current_url
                    had_error = True
                else:
                    candidates = []
                    for div in tax_listing.select("div[data-prefetch]"):
                        h3 = div.find("h3")
                        if not h3:
                            continue
                        a = h3.find("a")
                        if not a:
                            continue
                        href = a.get("href", "")
                        mst_in_href = href.strip("/").split("-")[0]
                        addr_tag = div.find("address")
                        candidates.append({
                            "ten":  h3.get_text(strip=True),
                            "mst":  mst_in_href,
                            "href": href,
                            "addr": addr_tag.get_text(strip=True) if addr_tag else "",
                        })

                    if not candidates:
                        record.loi = "Không tìm thấy kết quả"
                        record.url = current_url
                        had_error = True
                    else:
                        # Tìm khớp chính xác
                        best = next((c for c in candidates if q in c["href"]), None)
                        if not best:
                            best = next((c for c in candidates if c["mst"] == q), None)
                        if not best:
                            best = candidates[0]

                        # Vào trang chi tiết
                        detail_url = BASE + best["href"] if best["href"].startswith("/") else best["href"]
                        self.driver.get(detail_url)
                        time.sleep(random.uniform(0.8, 1.5))
                        
                        detail_soup = BeautifulSoup(self.driver.page_source, "html.parser")
                        info = _parse_detail_page(detail_soup)
                        
                        record.ten_nnt        = info.get("ten_nnt", best["ten"])
                        record.mst_result     = info.get("mst_result", best["mst"])
                        record.dia_chi_result = info.get("dia_chi_result", best["addr"])
                        record.co_quan_thue   = info.get("co_quan_thue", "")
                        record.trang_thai     = info.get("trang_thai", "")
                        record.url            = self.driver.current_url

        except Exception as e:
            record.loi = str(e)[:200]
            try:
                if self.driver:
                    record.url = self.driver.current_url
            except:
                pass

        return record


class ParallelTaxScraper:
    """Quản lý nhiều browser workers với profiles/tài khoản riêng"""
    
    def __init__(self, num_workers: int = 5, headless: bool = True, use_profiles: bool = True):
        """
        Args:
            num_workers: Số lượng browser instances chạy song song (mặc định 5)
            headless: Chạy ẩn hay hiện browser
            use_profiles: Sử dụng profiles riêng cho mỗi worker (khuyến nghị: True)
        """
        self.num_workers = num_workers
        self.headless = headless
        self.use_profiles = use_profiles
        self.workers: List[WorkerBrowser] = []
        self.print_lock = Lock()
        
        # Load config
        self.config = self._load_config()
        self.accounts = load_accounts()
        
    def _load_config(self) -> dict:
        """Load config từ file"""
        config_path = Path("config.json")
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
        
    def __enter__(self):
        self.start()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        
    def start(self):
        """Khởi động tất cả workers với profiles riêng"""
        parallel_config = self.config.get("parallel", {})
        profiles_dir = parallel_config.get("profiles_dir", "./browser_profiles")
        
        print(f"🚀 Khởi động {self.num_workers} browser workers...")
        if self.use_profiles:
            print(f"📁 Profiles directory: {profiles_dir}")
        
        for i in range(self.num_workers):
            # Lấy tài khoản tương ứng (nếu có)
            account = self.accounts[i] if i < len(self.accounts) else None
            
            worker = WorkerBrowser(
                worker_id=i+1, 
                headless=self.headless,
                account=account,
                use_profile=self.use_profiles,
                profiles_dir=profiles_dir
            )
            worker.start()
            self.workers.append(worker)
            print(f"  ✓ Worker {i+1} sẵn sàng")
        print()
        
    def close(self):
        """Đóng tất cả workers"""
        print("\n🔒 Đóng tất cả browsers...")
        for worker in self.workers:
            worker.close()
        self.workers = []
        print("✅ Đã đóng tất cả browsers")
        
    def _process_item(self, worker: WorkerBrowser, item: Dict, index: int, total: int) -> TaxRecord:
        """Xử lý 1 item với worker cụ thể"""
        mst = str(item.get("mst", "")).strip()
        if not mst:
            return TaxRecord(mst="", loi="MST trống")
        
        label = "(CCCD)" if len(mst) == 12 else "(MST)"
        
        with self.print_lock:
            account_info = f" [{worker.account.note}]" if worker.account else ""
            print(f"[Worker {worker.worker_id}{account_info}] [{index}/{total}] Tra cứu: {mst} {label}")
        
        result = worker.lookup_one(mst=mst, ho_ten=str(item.get("ho_ten", "") or ""))
        
        with self.print_lock:
            if result.loi:
                print(f"[Worker {worker.worker_id}]   ❌ {result.loi}")
            else:
                print(f"[Worker {worker.worker_id}]   ✅ {result.ten_nnt} | MST: {result.mst_result}")
        
        # Random delay giữa các request để tránh bị chặn
        time.sleep(random.uniform(0.5, 1.5))
        
        return result
    
    def lookup_batch(self, records_input: List[Dict]) -> List[TaxRecord]:
        """
        Tra cứu hàng loạt với parallel processing
        
        Args:
            records_input: List các dict chứa 'mst' và 'ho_ten'
            
        Returns:
            List TaxRecord theo đúng thứ tự input
        """
        total = len(records_input)
        if total == 0:
            return []
        
        print(f"🔍 Bắt đầu tra cứu {total} MST với {self.num_workers} workers...\n")
        
        # Tạo list kết quả với index để giữ đúng thứ tự
        results = [None] * total
        
        # Sử dụng ThreadPoolExecutor để chạy song song
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            # Submit tất cả tasks
            future_to_index = {}
            for i, item in enumerate(records_input):
                # Chọn worker theo round-robin
                worker = self.workers[i % self.num_workers]
                future = executor.submit(self._process_item, worker, item, i+1, total)
                future_to_index[future] = i
            
            # Thu thập kết quả
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result = future.result()
                    results[index] = result
                except Exception as e:
                    # Nếu có lỗi, tạo record lỗi
                    mst = str(records_input[index].get("mst", ""))
                    results[index] = TaxRecord(mst=mst, loi=f"Exception: {str(e)[:100]}")
        
        return results


if __name__ == "__main__":
    import sys
    
    # Test với 1 MST
    if len(sys.argv) > 1:
        mst = sys.argv[1]
        with ParallelTaxScraper(num_workers=1, headless=False, use_profiles=True) as scraper:
            r = scraper.lookup_batch([{"mst": mst}])[0]
            print(f"\n{'='*60}")
            print(f"Input:        {r.mst}")
            print(f"Tên NNT:      {r.ten_nnt}")
            print(f"MST:          {r.mst_result}")
            print(f"Địa chỉ:      {r.dia_chi_result}")
            print(f"CQ Thuế:      {r.co_quan_thue}")
            print(f"Trạng thái:   {r.trang_thai}")
            print(f"URL:          {r.url}")
            if r.loi:
                print(f"Lỗi:          {r.loi}")
    else:
        # Test với nhiều MST
        test_data = [
            {"mst": "079203002600"},
            {"mst": "0316589012"},
            {"mst": "0123456789"},
        ]
        
        with ParallelTaxScraper(num_workers=3, headless=False, use_profiles=True) as scraper:
            results = scraper.lookup_batch(test_data)
            
            print(f"\n{'='*60}")
            print("KẾT QUẢ:")
            for r in results:
                print(f"\n{r.mst}: {r.ten_nnt or r.loi}")
