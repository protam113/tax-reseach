#!/usr/bin/env python3
"""
Test CAPTCHA solving với nhiều ảnh
"""

import time
from scraper_gov import TaxGovScraper

def test_captcha_batch(num_tests=10):
    """Test giải CAPTCHA nhiều lần để thu thập data"""
    print(f"Testing CAPTCHA solving {num_tests} lần...\n")
    
    results = []
    
    with TaxGovScraper(headless=False) as scraper:
        for i in range(num_tests):
            print(f"\n{'='*50}")
            print(f"Test {i+1}/{num_tests}")
            print('='*50)
            
            try:
                # Load trang
                scraper.driver.get("https://tracuunnt.gdt.gov.vn/tcnnt/mstcn.jsp")
                time.sleep(2)
                
                # Giải CAPTCHA (sẽ save ảnh tự động)
                captcha_text = scraper._solve_captcha(max_retries=1, save_debug=True)
                
                result = {
                    'test': i+1,
                    'captcha': captcha_text,
                    'length': len(captcha_text) if captcha_text else 0,
                    'success': captcha_text and len(captcha_text) == 5
                }
                results.append(result)
                
                print(f"Result: {captcha_text} (len={result['length']}) - {'✅' if result['success'] else '❌'}")
                
                # Delay giữa các test
                if i < num_tests - 1:
                    time.sleep(3)
                    
            except Exception as e:
                print(f"Error: {e}")
                results.append({
                    'test': i+1,
                    'captcha': None,
                    'length': 0,
                    'success': False,
                    'error': str(e)
                })
    
    # Summary
    print(f"\n{'='*50}")
    print("SUMMARY")
    print('='*50)
    
    success_count = sum(1 for r in results if r['success'])
    print(f"Total tests: {len(results)}")
    print(f"Success: {success_count}/{len(results)} ({success_count/len(results)*100:.1f}%)")
    print(f"\nResults:")
    for r in results:
        status = '✅' if r['success'] else '❌'
        print(f"  Test {r['test']}: {r['captcha']} (len={r['length']}) {status}")
    
    print(f"\nẢnh CAPTCHA đã được save vào folder: captcha_debug/")
    print(f"Kiểm tra ảnh để xem tại sao EasyOCR đọc sai!")

if __name__ == "__main__":
    import sys
    num = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    test_captcha_batch(num)
