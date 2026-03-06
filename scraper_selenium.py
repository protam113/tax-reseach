"""
scraper_selenium.py - Dùng Selenium để bypass Cloudflare
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


def _parse_detail_page(soup: BeautifulSoup) -> dict:
    """Parse trang chi tiết: table.table-taxinfo"""
    result = {}
    table = soup.find("table", class_="table-taxinfo")
    if not table:
        return result

    # Tên từ thead
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


class TaxScraper:
    def __init__(self, headless=True):
        self.headless = headless
        self.driver = None
        
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
            
    def lookup_one(self, mst: str, ho_ten: str = "") -> TaxRecord:
        """Tra cứu 1 MST"""
        record = TaxRecord(mst=mst, ho_ten_input=ho_ten)
        q = mst.strip()
        
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
            
            # Đợi Cloudflare check (nếu có)
            time.sleep(2)
            
            # Đợi page load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Parse HTML
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            
            # Check xem đang ở trang nào
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
                        return record
                    else:
                        record.loi = f"MST {q} không tồn tại hoặc đã thay đổi (redirect về {mst_in_result})"
                        record.url = current_url
                        return record
            
            # Đang ở trang search - tìm trong listing
            tax_listing = soup.find("div", class_="tax-listing")
            if not tax_listing:
                record.loi = "Không tìm thấy kết quả"
                record.url = current_url
                return record

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
                return record

            # Tìm khớp chính xác
            best = next((c for c in candidates if q in c["href"]), None)
            if not best:
                best = next((c for c in candidates if c["mst"] == q), None)
            if not best:
                best = candidates[0]

            # Vào trang chi tiết
            detail_url = BASE + best["href"] if best["href"].startswith("/") else best["href"]
            self.driver.get(detail_url)
            time.sleep(1)
            
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
            # Try to capture URL even on error
            try:
                if self.driver:
                    record.url = self.driver.current_url
            except:
                pass

        return record
    
    def lookup_batch(self, records_input: list[dict]) -> list[TaxRecord]:
        """Tra cứu hàng loạt"""
        results = []
        total = len(records_input)
        
        for i, item in enumerate(records_input, 1):
            mst = str(item.get("mst", "")).strip()
            if not mst:
                continue
            label = "(CCCD)" if len(mst) == 12 else "(MST)"
            print(f"[{i}/{total}] Tra cứu: {mst} {label}")
            
            r = self.lookup_one(mst=mst, ho_ten=str(item.get("ho_ten", "") or ""))
            results.append(r)
            
            if r.loi:
                print(f"  ❌ {r.loi}")
            else:
                print(f"  ✅ {r.ten_nnt} | MST: {r.mst_result}")
            
            if i < total:
                time.sleep(random.uniform(2.0, 4.0))
                
        return results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        mst = sys.argv[1]
        with TaxScraper(headless=False) as scraper:
            r = scraper.lookup_one(mst)
            print(f"\nInput:        {r.mst}")
            print(f"Tên NNT:      {r.ten_nnt}")
            print(f"MST:          {r.mst_result}")
            print(f"Địa chỉ:      {r.dia_chi_result}")
            print(f"CQ Thuế:      {r.co_quan_thue}")
            print(f"Trạng thái:   {r.trang_thai}")
            if r.loi:
                print(f"Lỗi:          {r.loi}")
