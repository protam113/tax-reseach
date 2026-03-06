"""
collect_captcha_data.py - Thu thập captcha data để train CRNN

Chạy scraper nhiều lần để lấy captcha, tự động lưu vào train/data/
"""

import os
import time
import shutil
from pathlib import Path
from datetime import datetime
import requests
from scan_code import read_captcha_from_bytes

# Config
TARGET_IMAGES = 500  # Mục tiêu: 500 ảnh
CAPTCHA_URL = "https://tracuunnt.gdt.gov.vn/tcnnt/captcha.png"
OUTPUT_DIR = Path("train/data")
TEMP_DIR = Path("captcha_temp")

def download_captcha() -> bytes:
    """Download 1 captcha từ server"""
    try:
        response = requests.get(CAPTCHA_URL, timeout=10)
        if response.status_code == 200:
            return response.content
        return None
    except Exception as e:
        print(f"⚠️ Lỗi download: {e}")
        return None


def save_captcha(image_bytes: bytes, label: str, output_dir: Path) -> bool:
    """Lưu captcha với tên = label"""
    try:
        # Tạo tên file unique
        base_name = f"{label}.png"
        output_path = output_dir / base_name
        
        # Nếu file đã tồn tại, thêm _1, _2, ...
        counter = 1
        while output_path.exists():
            output_path = output_dir / f"{label}_{counter}.png"
            counter += 1
        
        # Lưu file
        with open(output_path, 'wb') as f:
            f.write(image_bytes)
        
        return True
    except Exception as e:
        print(f"⚠️ Lỗi lưu file: {e}")
        return False


def collect_data(target: int = TARGET_IMAGES):
    """Thu thập captcha data"""
    
    # Tạo thư mục
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    
    # Đếm số ảnh hiện có
    existing = len(list(OUTPUT_DIR.glob("*.png")))
    needed = target - existing
    
    if needed <= 0:
        print(f"✅ Đã có đủ {existing} ảnh (target: {target})")
        return
    
    print(f"📊 Hiện có: {existing} ảnh")
    print(f"🎯 Cần thêm: {needed} ảnh")
    print(f"🔄 Bắt đầu thu thập...\n")
    
    collected = 0
    failed = 0
    start_time = time.time()
    
    for i in range(needed * 2):  # x2 để bù cho lỗi
        if collected >= needed:
            break
        
        print(f"[{i+1}] ", end="", flush=True)
        
        # Download captcha
        image_bytes = download_captcha()
        if not image_bytes:
            print("❌ Download failed")
            failed += 1
            time.sleep(1)
            continue
        
        # OCR để lấy label
        try:
            label = read_captcha_from_bytes(image_bytes)
            
            # Validate label
            if not label or len(label) < 4 or len(label) > 5:
                print(f"⚠️ Label không hợp lệ: '{label}'")
                failed += 1
                continue
            
            # Lưu file
            if save_captcha(image_bytes, label, OUTPUT_DIR):
                collected += 1
                print(f"✅ Saved: {label} ({collected}/{needed})")
            else:
                failed += 1
                print(f"❌ Save failed")
        
        except Exception as e:
            print(f"❌ Error: {e}")
            failed += 1
        
        # Delay để không spam server
        time.sleep(0.5)
        
        # Progress report mỗi 10 ảnh
        if (i + 1) % 10 == 0:
            elapsed = time.time() - start_time
            rate = collected / elapsed if elapsed > 0 else 0
            eta = (needed - collected) / rate if rate > 0 else 0
            print(f"\n📊 Progress: {collected}/{needed} ({collected/needed*100:.1f}%)")
            print(f"   Rate: {rate:.1f} img/s | ETA: {eta/60:.1f} min\n")
    
    # Summary
    elapsed = time.time() - start_time
    total = existing + collected
    
    print("\n" + "=" * 60)
    print("📊 KẾT QUẢ THU THẬP")
    print("=" * 60)
    print(f"✅ Đã thu thập: {collected} ảnh mới")
    print(f"❌ Thất bại: {failed}")
    print(f"📁 Tổng cộng: {total} ảnh")
    print(f"⏱️ Thời gian: {elapsed/60:.1f} phút")
    print(f"🎯 Tiến độ: {total}/{target} ({total/target*100:.1f}%)")
    
    if total >= target:
        print(f"\n🎉 ĐÃ ĐẠT MỤC TIÊU {target} ẢNH!")
        print(f"\n📝 Next steps:")
        print(f"   1. Verify labels: python verify_labels.py")
        print(f"   2. Train CRNN: cd train && python train.py --data data --epochs 100")
    else:
        print(f"\n⚠️ Cần thêm {target - total} ảnh nữa")
        print(f"   Chạy lại: python collect_captcha_data.py")


def verify_existing_labels():
    """Kiểm tra labels của ảnh hiện có"""
    print("🔍 Kiểm tra labels hiện có...\n")
    
    image_files = sorted(list(OUTPUT_DIR.glob("*.png")))
    
    if not image_files:
        print("❌ Không có ảnh nào trong train/data/")
        return
    
    print(f"Tổng số ảnh: {len(image_files)}")
    
    # Kiểm tra độ dài label
    length_dist = {}
    for img_path in image_files:
        label = img_path.stem.split('_')[0]  # Bỏ _1, _2, ...
        length = len(label)
        length_dist[length] = length_dist.get(length, 0) + 1
    
    print("\nPhân bố độ dài label:")
    for length in sorted(length_dist.keys()):
        count = length_dist[length]
        print(f"  {length} ký tự: {count} ảnh ({count/len(image_files)*100:.1f}%)")
    
    # Kiểm tra ký tự
    all_chars = set()
    for img_path in image_files:
        label = img_path.stem.split('_')[0]
        all_chars.update(label)
    
    print(f"\nKý tự sử dụng: {''.join(sorted(all_chars))}")
    print(f"Tổng: {len(all_chars)} ký tự unique")
    
    # Kiểm tra ký tự không hợp lệ
    valid_chars = set('abcdefghkmnprwxy2345678')
    invalid = all_chars - valid_chars
    
    if invalid:
        print(f"\n⚠️ Ký tự không hợp lệ: {invalid}")
        print("   Cần kiểm tra lại labels!")
    else:
        print("\n✅ Tất cả ký tự đều hợp lệ")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Thu thập captcha data")
    parser.add_argument("--target", type=int, default=TARGET_IMAGES, help="Số ảnh mục tiêu")
    parser.add_argument("--verify", action="store_true", help="Chỉ verify labels hiện có")
    args = parser.parse_args()
    
    if args.verify:
        verify_existing_labels()
    else:
        collect_data(args.target)
