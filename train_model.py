"""
train_model.py - Train SVM classifier từ template DB của scan_code.py

Cách dùng:
    python train_model.py              # train và lưu model
    python train_model.py --evaluate   # train + đánh giá cross-validation

Model được lưu tại: captcha_svm.pkl
Trong scan_code.py, thêm vào read_captcha_from_gray():
    model = load_svm_model()
    if model: return predict_with_svm(model, crops)
"""

import cv2
import numpy as np
import pickle
from pathlib import Path
from collections import Counter

# Import trực tiếp từ scan_code.py hiện có
from scan_code import (
    find_char_boundaries,
    extract_features,
    augment_crop,
    CAPTCHA_LENGTH,
    TRAIN_DATA_DIR,
)

MODEL_PATH = Path(__file__).parent / 'captcha_svm.pkl'


# =====================================================================
# BUILD DATASET
# =====================================================================

def build_dataset(train_dir: Path = TRAIN_DATA_DIR, augment: bool = True):
    """
    Đọc toàn bộ ảnh labeled, segment + extract features.
    Returns X (n_samples, n_features), y (n_samples,)
    """
    img_files = sorted(train_dir.glob('*.png'))
    if not img_files:
        raise FileNotFoundError(f"Không tìm thấy ảnh trong {train_dir}")

    print(f"[TRAIN] Loading {len(img_files)} images...")
    X, y = [], []
    failed = 0

    for img_path in img_files:
        label = img_path.stem
        if len(label) != CAPTCHA_LENGTH:
            continue
        img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            failed += 1
            continue
        try:
            crops = find_char_boundaries(img)
            for ch, crop in zip(label, crops):
                variants = augment_crop(crop) if augment else [crop]
                for aug in variants:
                    X.append(extract_features(aug))
                    y.append(ch)
        except Exception as e:
            failed += 1
            continue

    X = np.array(X, dtype=np.float32)
    y = np.array(y)

    char_counts = Counter(y)
    print(f"[TRAIN] Dataset: {len(X)} samples, {len(char_counts)} classes")
    print(f"[TRAIN] Failed: {failed} images")
    print(f"[TRAIN] Samples per class (min/max): "
          f"{min(char_counts.values())}/{max(char_counts.values())}")

    return X, y


# =====================================================================
# TRAIN
# =====================================================================

def train(train_dir: Path = TRAIN_DATA_DIR, save_path: Path = MODEL_PATH):
    from sklearn.svm import SVC
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline

    X, y = build_dataset(train_dir, augment=True)

    print("[TRAIN] Training SVM (RBF kernel)...")
    model = Pipeline([
        ('scaler', StandardScaler()),
        ('svm', SVC(
            kernel='rbf',
            C=10.0,
            gamma='scale',
            probability=True,
            class_weight='balanced',
            random_state=42,
        ))
    ])

    model.fit(X, y)

    # Training accuracy (in-sample, expected ~100%)
    train_acc = model.score(X, y)
    print(f"[TRAIN] Training accuracy: {train_acc*100:.1f}%")

    with open(save_path, 'wb') as f:
        pickle.dump(model, f)
    print(f"[TRAIN] Model saved → {save_path} "
          f"({save_path.stat().st_size / 1024:.0f} KB)")

    return model


# =====================================================================
# EVALUATE (cross-validation)
# =====================================================================

def evaluate(train_dir: Path = TRAIN_DATA_DIR):
    from sklearn.svm import SVC
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn.model_selection import StratifiedKFold, cross_val_score

    # Dùng original samples KHÔNG augment để evaluate công bằng
    X, y = build_dataset(train_dir, augment=False)

    print("[EVAL] Running 5-fold cross-validation (no augmentation)...")
    model = Pipeline([
        ('scaler', StandardScaler()),
        ('svm', SVC(kernel='rbf', C=10.0, gamma='scale',
                    probability=True, class_weight='balanced')),
    ])

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(model, X, y, cv=cv, scoring='accuracy', n_jobs=-1)

    print(f"[EVAL] Per-char accuracy: {scores.mean()*100:.1f}% ± {scores.std()*100:.1f}%")

    # Ước tính CAPTCHA-level accuracy (tất cả 5 chars đúng)
    char_acc = scores.mean()
    captcha_acc = char_acc ** CAPTCHA_LENGTH
    print(f"[EVAL] Estimated CAPTCHA accuracy: {captcha_acc*100:.1f}%")
    print(f"       (assuming independent errors per position)")

    return scores


# =====================================================================
# LOAD HELPER (dùng trong scan_code.py nếu muốn)
# =====================================================================

def load_svm_model(model_path: Path = MODEL_PATH):
    """Load SVM model đã train. Dùng thay KNN trong scan_code.py."""
    if not model_path.exists():
        return None
    with open(model_path, 'rb') as f:
        return pickle.load(f)


def predict_with_svm(model, crops: list) -> tuple:
    """
    Predict 5 ký tự dùng SVM model.
    Returns (captcha_str, confidences_list)

    Dùng trong scan_code.py:
        from train_model import load_svm_model, predict_with_svm
        model = load_svm_model()
        result, confs = predict_with_svm(model, crops)
    """
    chars, confs = [], []
    for crop in crops:
        feat = extract_features(crop).reshape(1, -1)
        ch = model.predict(feat)[0]
        conf = float(model.predict_proba(feat)[0].max())
        chars.append(ch)
        confs.append(conf)
    return ''.join(chars), confs


# =====================================================================
# MAIN
# =====================================================================

if __name__ == "__main__":
    import sys

    if '--evaluate' in sys.argv:
        # Cross-validation trước, rồi train full model
        evaluate()
        print()

    # Luôn train và lưu model
    train()
    print("\n✅ Done! Dùng model trong scan_code.py:")
    print("   from train_model import load_svm_model, predict_with_svm")
    print("   model = load_svm_model()")
    print("   result, confs = predict_with_svm(model, crops)")