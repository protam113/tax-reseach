"""
scraper_cloud.py - Dùng cloudscraper để bypass Cloudflare
"""

import time
import random
import cloudscraper
from dataclasses import dataclass
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


# Tạo scraper instance
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'linux',
        'mobile': False
    }
)


def _get(url: str, params=None, retry=3):
    """Get with retry on 403"""
    for attempt in range(retry):
        try:
            resp = scraper.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt < retry - 1:
                wait_time = (attempt + 1) * 3
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


def lookup_one(mst: str, ho_ten: str = "") -> TaxRecord:
    record = TaxRecord(mst=mst, ho_ten_input=ho_ten)
    q = mst.strip()

    try:
        search_type = "auto"
        if len(q) == 10:
            search_type = "personalTax"
        elif len(q) == 12:
            search_type = "identity"
        
        params = {"q": q, "type": search_type}
        if len(q) == 12:
            params["force-search"] = "1"
        
        resp = _get(f"{BASE}/Search/", params=params)
        soup = BeautifulSoup(resp.text, "html.parser")

        final_url = resp.url
        is_search_page = "Search" in final_url
        
        if not is_search_page:
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
                    return record
                else:
                    record.loi = f"MST {q} không tồn tại (redirect về {mst_in_result})"
                    return record

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

        best = next((c for c in candidates if q in c["href"]), None)
        if not best:
            best = next((c for c in candidates if c["mst"] == q), None)
        if not best:
            best = candidates[0]

        detail_url = BASE + best["href"] if best["href"].startswith("/") else best["href"]
        detail_resp = _get(detail_url)
        detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
        info = _parse_detail_page(detail_soup)
        
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
            time.sleep(random.uniform(2.0, 4.0))
    return results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        q = sys.argv[1]
        r = lookup_one(q)
        print(f"\nInput:        {r.mst}")
        print(f"Tên NNT:      {r.ten_nnt}")
        print(f"MST:          {r.mst_result}")
        print(f"Địa chỉ:      {r.dia_chi_result}")
        print(f"CQ Thuế:      {r.co_quan_thue}")
        print(f"Trạng thái:   {r.trang_thai}")
        if r.loi:
            print(f"Lỗi:          {r.loi}")
