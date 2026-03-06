#!/usr/bin/env python3
"""
Test script to verify URL links are captured correctly
"""

from scraper_selenium import TaxScraper

def test_single_lookup():
    """Test single MST lookup and verify URL is captured"""
    print("Testing URL capture with Selenium (visible browser)...\n")
    
    test_mst = "8722700686"
    
    # Use headless=False like the GUI does
    with TaxScraper(headless=False) as scraper:
        result = scraper.lookup_one(test_mst)
        
        print(f"MST Input:    {result.mst}")
        print(f"Tên NNT:      {result.ten_nnt}")
        print(f"MST Result:   {result.mst_result}")
        print(f"Địa chỉ:      {result.dia_chi_result}")
        print(f"CQ Thuế:      {result.co_quan_thue}")
        print(f"Trạng thái:   {result.trang_thai}")
        print(f"URL:          {result.url}")
        print(f"Lỗi:          {result.loi}")
        
        if result.url:
            print(f"\n✅ URL captured successfully!")
            print(f"🔗 Link: {result.url}")
            
            if result.ten_nnt:
                print(f"\n✅ Data retrieved successfully!")
                return True
            else:
                print(f"\n⚠️  URL captured but no data (might be Cloudflare issue)")
                return True
        else:
            print(f"\n❌ URL not captured")
            return False

if __name__ == "__main__":
    success = test_single_lookup()
    exit(0 if success else 1)
