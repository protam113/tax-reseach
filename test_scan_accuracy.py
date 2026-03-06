"""
test_scan_accuracy.py - Test độ chính xác của scan_code.py

Chạy scan_code.py trên tất cả ảnh trong train/data/ và so sánh với ground truth
"""

import os
from pathlib import Path
from collections import defaultdict
import json
from datetime import datetime

# Import scan_code
from scan_code_svm import read_captcha_from_file


def analyze_errors(results: list[dict]) -> dict:
    """Phân tích lỗi chi tiết"""
    error_types = defaultdict(list)
    
    for r in results:
        if not r['correct']:
            gt = r['ground_truth']
            pred = r['predicted']
            
            # Phân loại lỗi
            if len(pred) != len(gt):
                error_types['length_mismatch'].append(r)
            elif pred == '':
                error_types['empty_prediction'].append(r)
            else:
                # Đếm số ký tự sai
                wrong_chars = sum(1 for a, b in zip(gt, pred) if a != b)
                if wrong_chars == 1:
                    error_types['1_char_wrong'].append(r)
                elif wrong_chars == 2:
                    error_types['2_chars_wrong'].append(r)
                else:
                    error_types['multiple_chars_wrong'].append(r)
    
    return error_types


def test_accuracy():
    """Test scan_code.py trên tất cả ảnh"""
    data_dir = Path('train/data')
    image_files = sorted(list(data_dir.glob('*.png')))
    
    if not image_files:
        print("❌ Không tìm thấy ảnh trong train/data/")
        return
    
    print(f"🔍 Test scan_code.py với {len(image_files)} ảnh...")
    print("=" * 70)
    
    results = []
    correct_count = 0
    
    for idx, img_path in enumerate(image_files, 1):
        ground_truth = img_path.stem  # Tên file = label
        
        print(f"\n[{idx}/{len(image_files)}] {img_path.name}")
        print(f"Ground truth: '{ground_truth}'")
        
        try:
            predicted = read_captcha_from_file(str(img_path))
            is_correct = predicted == ground_truth
            
            if is_correct:
                correct_count += 1
                print(f"✅ ĐÚNG: '{predicted}'")
            else:
                print(f"❌ SAI: '{predicted}' (expected: '{ground_truth}')")
            
            results.append({
                'filename': img_path.name,
                'ground_truth': ground_truth,
                'predicted': predicted,
                'correct': is_correct
            })
            
        except Exception as e:
            print(f"⚠️ LỖI: {e}")
            results.append({
                'filename': img_path.name,
                'ground_truth': ground_truth,
                'predicted': '',
                'correct': False,
                'error': str(e)
            })
    
    # Tính toán thống kê
    print("\n" + "=" * 70)
    print("📊 KẾT QUẢ TỔNG HỢP")
    print("=" * 70)
    
    accuracy = correct_count / len(results) * 100
    print(f"\n✅ Chính xác: {correct_count}/{len(results)} ({accuracy:.2f}%)")
    print(f"❌ Sai: {len(results) - correct_count}/{len(results)} ({100-accuracy:.2f}%)")
    
    # Phân tích lỗi
    error_types = analyze_errors(results)
    
    if error_types:
        print("\n📋 PHÂN TÍCH LỖI:")
        print("-" * 70)
        
        for error_type, items in sorted(error_types.items(), key=lambda x: len(x[1]), reverse=True):
            print(f"\n{error_type.replace('_', ' ').title()}: {len(items)} lỗi")
            
            # Hiển thị 5 ví dụ đầu
            for item in items[:5]:
                gt = item['ground_truth']
                pred = item['predicted']
                print(f"  • {item['filename']}: '{gt}' → '{pred}'")
            
            if len(items) > 5:
                print(f"  ... và {len(items) - 5} lỗi khác")
    
    # Phân tích ký tự bị nhầm nhiều nhất
    print("\n📊 KÝ TỰ BỊ NHẦM NHIỀU NHẤT:")
    print("-" * 70)
    
    char_errors = defaultdict(lambda: defaultdict(int))
    
    for r in results:
        if not r['correct'] and len(r['predicted']) == len(r['ground_truth']):
            for gt_char, pred_char in zip(r['ground_truth'], r['predicted']):
                if gt_char != pred_char:
                    char_errors[gt_char][pred_char] += 1
    
    # Sắp xếp theo số lần nhầm
    sorted_errors = []
    for gt_char, pred_dict in char_errors.items():
        for pred_char, count in pred_dict.items():
            sorted_errors.append((gt_char, pred_char, count))
    
    sorted_errors.sort(key=lambda x: x[2], reverse=True)
    
    for gt_char, pred_char, count in sorted_errors[:10]:
        print(f"  '{gt_char}' → '{pred_char}': {count} lần")
    
    # Lưu kết quả
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"scan_accuracy_report_{timestamp}.json"
    
    report = {
        'timestamp': timestamp,
        'total_images': len(results),
        'correct': correct_count,
        'accuracy': accuracy,
        'error_types': {k: len(v) for k, v in error_types.items()},
        'char_errors': {f"{gt}→{pred}": count for gt, pred, count in sorted_errors[:20]},
        'results': results
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 Đã lưu báo cáo chi tiết: {output_file}")
    
    # Khuyến nghị cải thiện
    print("\n💡 KHUYẾN NGHỊ CẢI THIỆN:")
    print("-" * 70)
    
    if accuracy < 50:
        print("⚠️ Accuracy rất thấp (<50%)")
        print("  → Kiểm tra lại preprocessing")
        print("  → Xem xét dùng model CRNN thay EasyOCR")
    elif accuracy < 70:
        print("⚠️ Accuracy trung bình (50-70%)")
        print("  → Cải thiện postprocessing rules")
        print("  → Thêm nhiều preprocessing variants")
    elif accuracy < 90:
        print("✓ Accuracy khá tốt (70-90%)")
        print("  → Fine-tune postprocessing cho các ký tự hay nhầm")
        print("  → Xem xét train CRNN model để đạt >95%")
    else:
        print("🎉 Accuracy rất tốt (>90%)")
        print("  → Có thể sử dụng trong production")
        print("  → Xem xét train CRNN để đạt 100%")
    
    if error_types.get('length_mismatch'):
        print(f"\n⚠️ Có {len(error_types['length_mismatch'])} lỗi về độ dài")
        print("  → Cải thiện OCR để đọc đủ ký tự")
        print("  → Kiểm tra preprocessing có làm mất ký tự không")
    
    if sorted_errors:
        top_confused = sorted_errors[0]
        print(f"\n⚠️ Ký tự hay nhầm nhất: '{top_confused[0]}' → '{top_confused[1]}' ({top_confused[2]} lần)")
        print(f"  → Thêm rule postprocessing cho cặp này")


if __name__ == "__main__":
    test_accuracy()
