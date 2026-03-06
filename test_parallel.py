"""
Test script để kiểm tra parallel mode
"""

from scraper_gov_parallel import ParallelTaxGovScraper

# Test data
test_data = [
    {"mst": "8379197494"},
    {"mst": "8561078574"},
    {"mst": "8812166853"},
    {"mst": "8666033316"},
    {"mst": "8550209056"},
]

def progress_callback(current, total, result):
    """Callback để theo dõi progress"""
    print(f"Progress: {current}/{total}")
    if result:
        print(f"  -> {result.mst}: {result.ten_nnt or result.loi}")

print("Testing parallel scraper with 3 workers...")
print(f"Total items: {len(test_data)}\n")

with ParallelTaxGovScraper(num_workers=3, headless=False, progress_callback=progress_callback) as scraper:
    results = scraper.lookup_batch(test_data)

print("\n" + "="*60)
print("FINAL RESULTS:")
print("="*60)
for i, r in enumerate(results, 1):
    print(f"{i}. MST: {r.mst}")
    print(f"   Tên: {r.ten_nnt}")
    print(f"   Lỗi: {r.loi}")
    print()
