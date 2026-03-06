"""
benchmark_parallel.py - Benchmark hiệu suất với số workers khác nhau
"""

import time
import sys
from scraper_parallel import ParallelTaxScraper

# Test data - có thể thay bằng data thật từ CSV
def generate_test_data(count=20):
    """Tạo test data với MST giả"""
    # Một số MST thật để test
    real_msts = [
        "079203002600",
        "0316589012", 
        "0100109106",
        "0301012345",
        "0123456789",
    ]
    
    data = []
    for i in range(count):
        # Lặp lại các MST thật
        mst = real_msts[i % len(real_msts)]
        data.append({"mst": mst, "ho_ten": f"Test {i+1}"})
    
    return data


def benchmark(num_items=20, workers_list=[1, 3, 5, 7]):
    """
    Benchmark với số lượng workers khác nhau
    
    Args:
        num_items: Số lượng MST cần tra cứu
        workers_list: List số workers cần test
    """
    print("=" * 80)
    print(f"BENCHMARK: Tra cứu {num_items} MST với số workers khác nhau")
    print("=" * 80)
    
    test_data = generate_test_data(num_items)
    results_table = []
    
    for num_workers in workers_list:
        print(f"\n{'─' * 80}")
        print(f"Testing với {num_workers} worker(s)...")
        print(f"{'─' * 80}")
        
        try:
            start = time.time()
            with ParallelTaxScraper(num_workers=num_workers, headless=True) as scraper:
                results = scraper.lookup_batch(test_data)
            elapsed = time.time() - start
            
            success = sum(1 for r in results if not r.loi)
            failed = len(results) - success
            
            results_table.append({
                'workers': num_workers,
                'time': elapsed,
                'success': success,
                'failed': failed,
                'avg_time': elapsed / num_items if num_items > 0 else 0
            })
            
            print(f"\n✅ Hoàn tất:")
            print(f"   Thời gian:     {elapsed:.2f}s")
            print(f"   Thành công:    {success}/{num_items}")
            print(f"   Thất bại:      {failed}/{num_items}")
            print(f"   TB/MST:        {elapsed/num_items:.2f}s")
            
        except Exception as e:
            print(f"\n❌ Lỗi: {str(e)}")
            results_table.append({
                'workers': num_workers,
                'time': 0,
                'success': 0,
                'failed': num_items,
                'avg_time': 0,
                'error': str(e)
            })
    
    # Hiển thị bảng tổng hợp
    print("\n" + "=" * 80)
    print("TỔNG HỢP KẾT QUẢ")
    print("=" * 80)
    print(f"{'Workers':<10} {'Thời gian':<12} {'Thành công':<12} {'TB/MST':<12} {'Tăng tốc':<10}")
    print("-" * 80)
    
    baseline_time = results_table[0]['time'] if results_table else 0
    
    for r in results_table:
        if 'error' in r:
            print(f"{r['workers']:<10} {'ERROR':<12} {'-':<12} {'-':<12} {'-':<10}")
        else:
            speedup = baseline_time / r['time'] if r['time'] > 0 else 0
            print(f"{r['workers']:<10} {r['time']:.2f}s{'':<6} "
                  f"{r['success']}/{num_items}{'':<6} "
                  f"{r['avg_time']:.2f}s{'':<6} "
                  f"{speedup:.2f}x")
    
    print("=" * 80)
    
    # Khuyến nghị
    if len(results_table) > 1:
        best = min([r for r in results_table if 'error' not in r], 
                   key=lambda x: x['time'])
        print(f"\n💡 KHUYẾN NGHỊ:")
        print(f"   Tốt nhất: {best['workers']} workers")
        print(f"   Thời gian: {best['time']:.2f}s")
        print(f"   Tăng tốc: {baseline_time/best['time']:.2f}x so với 1 worker")
        
        # Tính efficiency (speedup / workers)
        efficiency = (baseline_time / best['time']) / best['workers']
        print(f"   Hiệu suất: {efficiency:.2f} (1.0 = lý tưởng)")
        
        if efficiency < 0.5:
            print(f"\n⚠️  Cảnh báo: Hiệu suất thấp, có thể do:")
            print(f"   - Mạng chậm hoặc không ổn định")
            print(f"   - Server bị giới hạn tốc độ")
            print(f"   - Máy không đủ tài nguyên")


def quick_test():
    """Test nhanh với 5 MST"""
    print("Quick test với 5 MST, workers: 1, 3, 5")
    benchmark(num_items=5, workers_list=[1, 3, 5])


def standard_test():
    """Test chuẩn với 20 MST"""
    print("Standard test với 20 MST, workers: 1, 3, 5, 7")
    benchmark(num_items=20, workers_list=[1, 3, 5, 7])


def full_test():
    """Test đầy đủ với 50 MST"""
    print("Full test với 50 MST, workers: 1, 3, 5, 7, 10")
    benchmark(num_items=50, workers_list=[1, 3, 5, 7, 10])


if __name__ == "__main__":
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        
        if mode == "quick":
            quick_test()
        elif mode == "standard":
            standard_test()
        elif mode == "full":
            full_test()
        elif mode == "custom":
            # Custom benchmark
            num_items = int(sys.argv[2]) if len(sys.argv) > 2 else 20
            workers = [int(w) for w in sys.argv[3].split(",")] if len(sys.argv) > 3 else [1, 3, 5]
            benchmark(num_items=num_items, workers_list=workers)
        else:
            print("Usage:")
            print("  python benchmark_parallel.py quick      # 5 MST, workers: 1,3,5")
            print("  python benchmark_parallel.py standard   # 20 MST, workers: 1,3,5,7")
            print("  python benchmark_parallel.py full       # 50 MST, workers: 1,3,5,7,10")
            print("  python benchmark_parallel.py custom <num_items> <workers>")
            print("    Example: python benchmark_parallel.py custom 30 1,5,10")
    else:
        # Mặc định chạy standard test
        standard_test()
