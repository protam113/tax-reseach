"""
scraper.py — masothue.com

Cấu trúc trang:
- CCCD 12 số → /Search/?q=...  → trong div.tax-listing có các div[data-prefetch]
- MST 10 số  → /Search/?q=...  → redirect hoặc ra 1 kết quả → vào trang chi tiết
- Trang chi tiết MST            → table.table-taxinfo
"""

import time
import random
import requests
from dataclasses import dataclass
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    "Referer": "https://masothue.com/",
}

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


def _get(url: str, params=None, retry=3) -> requests.Response:
    """Get with retry on 403 Forbidden"""
    for attempt in range(retry):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return resp
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403 and attempt < retry - 1:
                # Rate limited, wait longer
                wait_time = (attempt + 1) * 3  # 3s, 6s, 9s
                time.sleep(wait_time)
                continue
            raise
    return resp


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
            # Lấy text từ span.copy hoặc toàn bộ th
            span = th.find("span", class_="copy")
            result["ten_nnt"] = span.get_text(strip=True) if span else th.get_text(strip=True)

    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        key = cells[0].get_text(" ", strip=True).lower()
        
        # Lấy MST từ span.copy nếu có
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
            # Lấy text từ <a> tag nếu có
            a_tag = cells[1].find("a")
            if a_tag:
                result["trang_thai"] = a_tag.get_text(strip=True)
            else:
                result["trang_thai"] = cells[1].get_text(" ", strip=True)

    return result


def _lookup_detail(href: str) -> dict:
    """Vào trang chi tiết và parse"""
    url = BASE + href if href.startswith("/") else href
    resp = _get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    return _parse_detail_page(soup)


def lookup_one(mst: str, ho_ten: str = "") -> TaxRecord:
    record = TaxRecord(mst=mst, ho_ten_input=ho_ten)
    q = mst.strip()

    try:
        # Xác định loại search dựa trên độ dài MST
        # MST cá nhân: 10 số, CCCD: 12 số
        search_type = "auto"
        if len(q) == 10:
            # Có thể là MST cá nhân, thử với personalTax
            search_type = "personalTax"
        elif len(q) == 12:
            # CCCD, dùng force-search để hiển thị list
            search_type = "identity"
        
        params = {"q": q, "type": search_type}
        if len(q) == 12:
            params["force-search"] = "1"
        
        resp = _get(f"{BASE}/Search/", params=params)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Kiểm tra xem đang ở trang nào
        final_url = resp.url
        is_search_page = "Search" in final_url
        
        if not is_search_page:
            # Đã redirect về trang chi tiết
            has_table = soup.find("table", class_="table-taxinfo") is not None
            if has_table:
                info = _parse_detail_page(soup)
                mst_in_result = info.get("mst_result", "")
                
                if mst_in_result == q:
                    # MST khớp chính xác
                    record.ten_nnt        = info.get("ten_nnt", "")
                    record.mst_result     = mst_in_result
                    record.dia_chi_result = info.get("dia_chi_result", "")
                    record.co_quan_thue   = info.get("co_quan_thue", "")
                    record.trang_thai     = info.get("trang_thai", "")
                    return record
                else:
                    # Redirect về MST khác
                    record.loi = f"MST {q} không tồn tại (redirect về {mst_in_result})"
                    return record

        # Đang ở trang search — tìm trong div.tax-listing
        tax_listing = soup.find("div", class_="tax-listing")
        if not tax_listing:
            record.loi = "Không tìm thấy kết quả"
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
            return record

        # Tìm khớp chính xác q trong href
        best = next((c for c in candidates if q in c["href"]), None)
        if not best:
            best = next((c for c in candidates if c["mst"] == q), None)
        if not best:
            best = candidates[0]

        # Vào trang chi tiết để lấy đầy đủ thông tin
        info = _lookup_detail(best["href"])
        record.ten_nnt        = info.get("ten_nnt", best["ten"])
        record.mst_result     = info.get("mst_result", best["mst"])
        record.dia_chi_result = info.get("dia_chi_result", best["addr"])
        record.co_quan_thue   = info.get("co_quan_thue", "")
        record.trang_thai     = info.get("trang_thai", "")

    except Exception as e:
        record.loi = str(e)[:200]

    return record


def lookup_batch(records_input: list[dict]) -> list[TaxRecord]:
    results = []
    total = len(records_input)
    
    # Delay ban đầu để tránh bị chặn
    if total > 0:
        time.sleep(2)
    
    for i, item in enumerate(records_input, 1):
        mst = str(item.get("mst", "")).strip()
        if not mst:
            continue
        label = "(CCCD)" if len(mst) == 12 else "(MST)"
        print(f"[{i}/{total}] Tra cứu: {mst} {label}")
        r = lookup_one(mst=mst, ho_ten=str(item.get("ho_ten", "") or ""))
        results.append(r)
        if r.loi:
            print(f"  ❌ {r.loi}")
        else:
            print(f"  ✅ {r.ten_nnt} | MST: {r.mst_result} | {r.dia_chi_result[:60]}")
        if i < total:
            time.sleep(random.uniform(2.0, 4.0))  # Tăng delay để tránh bị chặn
    return results


if __name__ == "__main__":
    import sys
    
    # Test với file HTML đã lưu
    if len(sys.argv) > 1 and sys.argv[1].endswith('.html'):
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            html = f.read()
        soup = BeautifulSoup(html, "html.parser")
        
        # Kiểm tra xem có phải trang chi tiết không
        table = soup.find("table", class_="table-taxinfo")
        if table:
            print("✅ Tìm thấy table-taxinfo - đây là trang chi tiết")
            info = _parse_detail_page(soup)
            print(f"Tên NNT:      {info.get('ten_nnt', 'N/A')}")
            print(f"MST:          {info.get('mst_result', 'N/A')}")
            print(f"Địa chỉ:      {info.get('dia_chi_result', 'N/A')}")
            print(f"CQ Thuế:      {info.get('co_quan_thue', 'N/A')}")
            print(f"Trạng thái:   {info.get('trang_thai', 'N/A')}")
        else:
            print("❌ Không tìm thấy table-taxinfo - đây là trang search")
            tax_listing = soup.find("div", class_="tax-listing")
            if tax_listing:
                candidates = []
                for div in tax_listing.select("div[data-prefetch]"):
                    h3 = div.find("h3")
                    if h3:
                        a = h3.find("a")
                        if a:
                            print(f"  - {h3.get_text(strip=True)}")
                            print(f"    href: {a.get('href', '')}")
    else:
        q = sys.argv[1] if len(sys.argv) > 1 else "079203002600"
        r = lookup_one(q)
        print(f"\nInput:        {r.mst}")
        print(f"Tên NNT:      {r.ten_nnt}")
        print(f"MST:          {r.mst_result}")
        print(f"Địa chỉ:      {r.dia_chi_result}")
        print(f"CQ Thuế:      {r.co_quan_thue}")
        print(f"Trạng thái:   {r.trang_thai}")
        if r.loi:
            print(f"Lỗi:          {r.loi}")