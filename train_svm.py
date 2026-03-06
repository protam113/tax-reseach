"""
train_svm.py
============
Script train SVM từ ảnh CAPTCHA đã được label.

Cấu trúc thư mục:
  train/data/
    r57pn.png       ← tên file = ground truth (5 ký tự)
    ra526.png
    ...

Cách dùng:
  python train_svm.py                    # train bình thường
  python train_svm.py --data ./mydata    # chỉ định thư mục khác
  python train_svm.py --eval             # train + đánh giá cross-validation
"""

import cv2
import numpy as np
import pickle
import argparse
from pathlib import Path
from collections import Counter
import sys

# ── Copy các hàm dùng chung từ scan_code_svm_v6.py ──────────────────────────
CAPTCHA_LENGTH = 5
CHAR_H, CHAR_W = 40, 28
SVM_PATH = Path(__file__).parent / 'captcha_svm.pkl'
TRAIN_DATA_DIR = Path(__file__).parent / 'train' / 'data'


def extract_features(crop_binary: np.ndarray) -> np.ndarray:
    resized = cv2.resize(crop_binary, (CHAR_W, CHAR_H), interpolation=cv2.INTER_AREA)
    pixel_feat = resized.flatten().astype(np.float32) / 255.0
    h_proj = resized.sum(axis=1).astype(np.float32)
    if h_proj.max() > 0:
        h_proj /= h_proj.max()
    v_proj = resized.sum(axis=0).astype(np.float32)
    if v_proj.max() > 0:
        v_proj /= v_proj.max()
    zones = []
    for zy in range(4):
        for zx in range(4):
            y1, y2 = zy * 10, (zy + 1) * 10
            x1, x2 = zx * 7, (zx + 1) * 7
            zone = resized[y1:y2, x1:x2]
            zones.append(zone.mean() / 255.0)
    zone_feat = np.array(zones, dtype=np.float32)
    return np.concatenate([pixel_feat, h_proj, v_proj, zone_feat])


def augment_crop(crop_binary: np.ndarray) -> list:
    """Tăng cường dữ liệu: dịch chuyển, scale"""
    h, w = crop_binary.shape
    variants = [crop_binary]
    # Dịch ngang
    for dx in [-2, -1, 1, 2]:
        M = np.float32([[1, 0, dx], [0, 1, 0]])
        variants.append(cv2.warpAffine(crop_binary, M, (w, h),
                                       borderMode=cv2.BORDER_CONSTANT, borderValue=0))
    # Dịch dọc
    for dy in [-1, 1]:
        M = np.float32([[1, 0, 0], [0, 1, dy]])
        variants.append(cv2.warpAffine(crop_binary, M, (w, h),
                                       borderMode=cv2.BORDER_CONSTANT, borderValue=0))
    # Scale nhẹ
    for scale in [0.92, 1.08]:
        scaled = cv2.resize(crop_binary, None, fx=scale, fy=scale,
                            interpolation=cv2.INTER_AREA)
        sh, sw = scaled.shape
        canvas = np.zeros((h, w), dtype=np.uint8)
        y_off = max(0, (h - sh) // 2)
        x_off = max(0, (w - sw) // 2)
        canvas[y_off:y_off + min(sh, h - y_off),
               x_off:x_off + min(sw, w - x_off)] = \
            scaled[:min(sh, h - y_off), :min(sw, w - x_off)]
        variants.append(canvas)
    return variants


def find_char_boundaries(img_gray: np.ndarray, n: int = CAPTCHA_LENGTH) -> list:
    scale = 4
    big = cv2.resize(img_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = thresh.shape
    proj = thresh.sum(axis=0).astype(float)
    ks = max(3, w // 40)
    proj_smooth = np.convolve(proj, np.ones(ks) / ks, mode='same')
    nonzero = np.where(proj_smooth > proj_smooth.max() * 0.05)[0]
    left = int(nonzero[0]) if len(nonzero) >= 10 else 0
    right = int(nonzero[-1]) if len(nonzero) >= 10 else w
    char_w = (right - left) / n
    boundaries = [left]
    for i in range(1, n):
        expected = int(left + i * char_w)
        sr = int(char_w * 0.4)
        ss, se = max(left, expected - sr), min(right, expected + sr)
        valley = int(np.argmin(proj_smooth[ss:se])) + ss if se > ss else expected
        boundaries.append(valley)
    boundaries.append(right)
    crops = []
    for i in range(n):
        x1, x2 = boundaries[i], boundaries[i + 1]
        crop = thresh[:, max(0, x1 - 3):min(w, x2 + 3)]
        if crop.shape[1] < 5:
            crop = thresh[:, int(left + i * char_w):min(w, int(left + (i + 1) * char_w))]
        crops.append(cv2.resize(crop, (CHAR_W, CHAR_H), interpolation=cv2.INTER_AREA))
    return crops


# ── Load data ────────────────────────────────────────────────────────────────

def load_training_data(train_dir: Path, use_augment: bool = True):
    """
    Đọc tất cả ảnh trong train_dir, extract features cho từng ký tự.
    Returns: X (n_samples, n_features), y (n_samples,)
    """
    img_files = sorted(train_dir.glob('*.png'))
    if not img_files:
        print(f"[ERROR] Không tìm thấy ảnh PNG trong: {train_dir}")
        sys.exit(1)

    X, y = [], []
    skipped = 0
    label_counter = Counter()

    print(f"[INFO] Đang load {len(img_files)} ảnh từ {train_dir} ...")

    for img_path in img_files:
        label = img_path.stem  # tên file không có .png = ground truth
        if len(label) != CAPTCHA_LENGTH:
            skipped += 1
            continue

        img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            skipped += 1
            continue

        try:
            crops = find_char_boundaries(img)
        except Exception as e:
            skipped += 1
            continue

        if len(crops) != CAPTCHA_LENGTH:
            skipped += 1
            continue

        for ch, crop in zip(label, crops):
            if use_augment:
                for aug in augment_crop(crop):
                    X.append(extract_features(aug))
                    y.append(ch)
                    label_counter[ch] += 1
            else:
                X.append(extract_features(crop))
                y.append(ch)
                label_counter[ch] += 1

    print(f"[INFO] Load xong: {len(X)} samples, {len(label_counter)} classes")
    print(f"[INFO] Bỏ qua: {skipped} ảnh (label sai độ dài hoặc đọc lỗi)")
    print(f"[INFO] Phân bố top-10 ký tự: {label_counter.most_common(10)}")

    if len(X) == 0:
        print("[ERROR] Không có data để train!")
        sys.exit(1)

    return np.array(X, dtype=np.float32), np.array(y)


# ── Train ────────────────────────────────────────────────────────────────────

def train_svm(X: np.ndarray, y: np.ndarray, do_eval: bool = False):
    from sklearn.svm import SVC
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn.model_selection import cross_val_score, StratifiedKFold

    print(f"\n[TRAIN] Bắt đầu train SVM ...")
    print(f"  X shape: {X.shape}")
    print(f"  Classes : {sorted(set(y))}")

    # Pipeline: chuẩn hoá + SVM RBF
    pipeline = Pipeline([
        ('scaler', StandardScaler()),
        ('svm', SVC(
            kernel='rbf',
            C=10,
            gamma='scale',
            probability=True,   # BẮT BUỘC để dùng predict_proba cho top-2 rules
            class_weight='balanced',
            random_state=42,
            cache_size=500,
        ))
    ])

    if do_eval:
        print("\n[EVAL] Cross-validation 5-fold ...")
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        scores = cross_val_score(pipeline, X, y, cv=cv, scoring='accuracy', n_jobs=-1)
        print(f"  Per-char accuracy: {scores}")
        print(f"  Mean: {scores.mean():.4f} ± {scores.std():.4f}")
        # Ước tính captcha-level accuracy (5 ký tự độc lập)
        char_acc = scores.mean()
        captcha_acc = char_acc ** CAPTCHA_LENGTH
        print(f"  Ước tính CAPTCHA accuracy (5^char): {captcha_acc:.4f} ({captcha_acc*100:.1f}%)")
        print()

    print("[TRAIN] Fitting toàn bộ data ...")
    pipeline.fit(X, y)
    print("[TRAIN] Done!")
    return pipeline


# ── Save ─────────────────────────────────────────────────────────────────────

def save_model(model, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as f:
        pickle.dump(model, f)
    print(f"[SAVE] Model saved → {path}")


# ── Quick test ───────────────────────────────────────────────────────────────

def quick_test(model, train_dir: Path, n_test: int = 30):
    """Test nhanh trên một số ảnh để kiểm tra model."""
    img_files = sorted(train_dir.glob('*.png'))[:n_test]
    correct = 0
    total = 0
    errors = []

    print(f"\n[TEST] Quick test trên {len(img_files)} ảnh ...")
    for img_path in img_files:
        label = img_path.stem
        if len(label) != CAPTCHA_LENGTH:
            continue
        img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        try:
            crops = find_char_boundaries(img)
        except Exception:
            continue

        pred_chars = []
        for crop in crops:
            feat = extract_features(crop).reshape(1, -1)
            proba = model.predict_proba(feat)[0]
            classes = list(model.classes_)
            pred_chars.append(classes[int(np.argmax(proba))])
        pred = ''.join(pred_chars)

        total += 1
        if pred == label:
            correct += 1
        else:
            errors.append((label, pred))

    if total > 0:
        print(f"  Correct: {correct}/{total} = {correct/total*100:.1f}%")
        if errors:
            print(f"  Errors: {errors[:10]}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Train SVM cho CAPTCHA reader')
    parser.add_argument('--data', type=str, default=str(TRAIN_DATA_DIR),
                        help='Đường dẫn thư mục chứa ảnh train')
    parser.add_argument('--output', type=str, default=str(SVM_PATH),
                        help='Đường dẫn lưu model')
    parser.add_argument('--eval', action='store_true',
                        help='Chạy cross-validation để đánh giá')
    parser.add_argument('--no-augment', action='store_true',
                        help='Tắt data augmentation (train nhanh hơn, kém hơn)')
    parser.add_argument('--test', action='store_true',
                        help='Quick test sau khi train')
    args = parser.parse_args()

    train_dir = Path(args.data)
    if not train_dir.exists():
        print(f"[ERROR] Thư mục không tồn tại: {train_dir}")
        print(f"  Tạo thư mục và bỏ ảnh vào đó: {train_dir}")
        sys.exit(1)

    # 1. Load data
    X, y = load_training_data(train_dir, use_augment=not args.no_augment)

    # 2. Train
    model = train_svm(X, y, do_eval=args.eval)

    # 3. Save
    save_model(model, Path(args.output))

    # 4. Quick test (optional)
    if args.test:
        quick_test(model, train_dir)

    print("\n✅ Xong! Giờ chạy lại accuracy test để kiểm tra cải thiện.")


if __name__ == '__main__':
    main()