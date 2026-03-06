"""
test_parallel.py - Test parallel scraping với nhiều MST
"""

import time
from scraper_parallel import ParallelTaxScraper

# Test data - một số MST thật để test
test_data = [
    {"mst": "079203002600", "ho_ten": "Test 1"},
    {"mst": "0316589012", "ho_ten": "Test 2"},
    {"mst": "0123456789", "ho_ten": "Test 3"},
    {"mst": "0987654321", "ho_ten": "Test 4"},
    {"mst": "0100109106", "ho_ten": "Test 5"},
]


def test_single_worker():
    """Test với 1 worker (tuần tự)"""
    print("=" * 70)
    print("TEST 1: Single Worker (Tuần tự)")
    print("=" * 70)
    
    start = time.time()
    with ParallelTaxScraper(num_workers=1, headless=True) as scraper:
        results = scraper.lookup_batch(test_data)
    elapsed = time.time() - start
    
    print(f"\n{'=' * 70}")
    print(f"Thời gian: {elapsed:.2f}s")
    print(f"Thành công: {sum(1 for r in results if not r.loi)}/{len(results)}")
    print("=" * 70)
    
    return elapsed, results


def test_parallel_workers(num_workers=3):
    """Test với nhiều workers"""
    print(f"\n{'=' * 70}")
    print(f"TEST 2: {num_workers} Workers (Parallel)")
    print("=" * 70)
    
    start = time.time()
    with ParallelTaxScraper(num_workers=num_workers, headless=True) as scraper:
        results = scraper.lookup_batch(test_data)
    elapsed = time.time() - start
    
    print(f"\n{'=' * 70}")
    print(f"Thời gian: {elapsed:.2f}s")
    print(f"Thành công: {sum(1 for r in results if not r.loi)}/{len(results)}")
    print("=" * 70)
    
    return elapsed, results


def compare_results():
    """So sánh hiệu suất giữa single và parallel"""
    print("\n" + "=" * 70)
    print("SO SÁNH HIỆU SUẤT")
    print("=" * 70)
    
    # Test với 1 worker
    time_single, results_single = test_single_worker()
    
    # Test với 3 workers
    time_parallel, results_parallel = test_parallel_workers(num_workers=3)
    
    # So sánh
    speedup = time_single / time_parallel if time_parallel > 0 else 0
    
    print(f"\n{'=' * 70}")
    print("KẾT QUẢ SO SÁNH:")
    print(f"  Single worker:   {time_single:.2f}s")
    print(f"  Parallel (3):    {time_parallel:.2f}s")
    print(f"  Tăng tốc:        {speedup:.2f}x")
    print(f"  Tiết kiệm:       {time_single - time_parallel:.2f}s ({(1 - time_parallel/time_single)*100:.1f}%)")
    print("=" * 70)
    
    # Hiển thị kết quả chi tiết
    print("\nKẾT QUẢ CHI TIẾT:")
    print("-" * 70)
    for i, r in enumerate(results_parallel, 1):
        status = "✅" if not r.loi else "❌"
        print(f"{status} {i}. {r.mst}")
        if r.ten_nnt:
            print(f"   Tên: {r.ten_nnt}")
            print(f"   MST: {r.mst_result}")
            print(f"   Địa chỉ: {r.dia_chi_result[:60]}...")
        else:
            print(f"   Lỗi: {r.loi}")
        print()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "single":
            test_single_worker()
        elif sys.argv[1] == "parallel":
            num = int(sys.argv[2]) if len(sys.argv) > 2 else 3
            test_parallel_workers(num)
        elif sys.argv[1] == "compare":
            compare_results()
        else:
            print("Usage:")
            print("  python test_parallel.py single")
            print("  python test_parallel.py parallel [num_workers]")
            print("  python test_parallel.py compare")
    else:
        # Mặc định chạy compare
        compare_results()
