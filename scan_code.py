"""
scan_code.py - CAPTCHA reader: KNN + SVM hybrid

Giữ nguyên toàn bộ code KNN cũ, chỉ thêm SVM làm primary classifier.
SVM load từ captcha_svm.pkl (train bằng train_model.py).
Fallback: KNN -> EasyOCR theo confidence.
"""

import cv2
import numpy as np
from PIL import Image
import easyocr
import re
import pickle
from pathlib import Path
from collections import Counter

CAPTCHA_LENGTH = 5
CHAR_H, CHAR_W = 40, 28
KNN_K = 5
KNN_CONF_THRESHOLD = 0.5
SVM_CONF_THRESHOLD = 0.6
DB_PATH = Path(__file__).parent / 'template_db.pkl'
SVM_PATH = Path(__file__).parent / 'captcha_svm.pkl'
TRAIN_DATA_DIR = Path(__file__).parent / 'train' / 'data'

_knn_db = None
_svm_model = None
_reader = None


# =====================================================================
# FEATURE EXTRACTION (không đổi)
# =====================================================================

def extract_features(crop_binary: np.ndarray) -> np.ndarray:
    resized = cv2.resize(crop_binary, (CHAR_W, CHAR_H), interpolation=cv2.INTER_AREA)
    pixel_feat = resized.flatten().astype(np.float32) / 255.0
    h_proj = resized.sum(axis=1).astype(np.float32)
    if h_proj.max() > 0: h_proj /= h_proj.max()
    v_proj = resized.sum(axis=0).astype(np.float32)
    if v_proj.max() > 0: v_proj /= v_proj.max()
    zones = []
    for zy in range(4):
        for zx in range(4):
            y1, y2 = zy*10, (zy+1)*10
            x1, x2 = zx*7, (zx+1)*7
            zone = resized[y1:y2, x1:x2]
            zones.append(zone.mean() / 255.0)
    zone_feat = np.array(zones, dtype=np.float32)
    return np.concatenate([pixel_feat, h_proj, v_proj, zone_feat])


def augment_crop(crop_binary: np.ndarray) -> list:
    h, w = crop_binary.shape
    variants = [crop_binary]
    for dx in [-2, -1, 1, 2]:
        M = np.float32([[1, 0, dx], [0, 1, 0]])
        variants.append(cv2.warpAffine(crop_binary, M, (w, h),
                                        borderMode=cv2.BORDER_CONSTANT, borderValue=0))
    for dy in [-1, 1]:
        M = np.float32([[1, 0, 0], [0, 1, dy]])
        variants.append(cv2.warpAffine(crop_binary, M, (w, h),
                                        borderMode=cv2.BORDER_CONSTANT, borderValue=0))
    for scale in [0.92, 1.08]:
        scaled = cv2.resize(crop_binary, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        sh, sw = scaled.shape
        canvas = np.zeros((h, w), dtype=np.uint8)
        y_off = max(0, (h - sh) // 2)
        x_off = max(0, (w - sw) // 2)
        canvas[y_off:y_off+min(sh,h-y_off), x_off:x_off+min(sw,w-x_off)] = \
            scaled[:min(sh,h-y_off), :min(sw,w-x_off)]
        variants.append(canvas)
    return variants


# =====================================================================
# SEGMENTATION (không đổi)
# =====================================================================

def find_char_boundaries(img_gray: np.ndarray, n: int = CAPTCHA_LENGTH) -> list:
    scale = 4
    big = cv2.resize(img_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = thresh.shape
    proj = thresh.sum(axis=0).astype(float)
    ks = max(3, w // 40)
    proj_smooth = np.convolve(proj, np.ones(ks) / ks, mode='same')
    nonzero = np.where(proj_smooth > proj_smooth.max() * 0.05)[0]
    left  = int(nonzero[0])  if len(nonzero) >= 10 else 0
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
        crop = thresh[:, max(0,x1-3):min(w,x2+3)]
        if crop.shape[1] < 5:
            crop = thresh[:, int(left+i*char_w):min(w,int(left+(i+1)*char_w))]
        crops.append(cv2.resize(crop, (CHAR_W, CHAR_H), interpolation=cv2.INTER_AREA))
    return crops


# =====================================================================
# SVM (primary classifier)
# =====================================================================

def load_svm():
    global _svm_model
    if _svm_model is not None:
        return _svm_model
    if SVM_PATH.exists():
        try:
            with open(SVM_PATH, 'rb') as f:
                _svm_model = pickle.load(f)
            print(f"[SVM] Loaded from {SVM_PATH}")
        except Exception as e:
            print(f"[SVM] Load failed: {e}")
    return _svm_model


def svm_predict(crop: np.ndarray) -> tuple:
    """Returns (char, confidence)"""
    model = load_svm()
    if model is None:
        return '?', 0.0
    feat = extract_features(crop).reshape(1, -1)
    char = model.predict(feat)[0]
    conf = float(model.predict_proba(feat)[0].max())
    return char, conf


# =====================================================================
# KNN (fallback khi SVM confidence thấp, không đổi)
# =====================================================================

def build_template_db(train_dir: Path = TRAIN_DATA_DIR) -> dict:
    db = {}
    img_files = sorted(train_dir.glob('*.png'))
    if not img_files:
        return db
    print(f"[KNN] Building DB from {len(img_files)} images...")
    for img_path in img_files:
        label = img_path.stem
        if len(label) != CAPTCHA_LENGTH: continue
        img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        if img is None: continue
        try:
            crops = find_char_boundaries(img)
            for ch, crop in zip(label, crops):
                if ch not in db: db[ch] = []
                for aug in augment_crop(crop):
                    db[ch].append(extract_features(aug))
        except Exception:
            continue
    print(f"[KNN] DB ready: {len(db)} chars, {sum(len(v) for v in db.values())} samples")
    return db


def load_or_build_db() -> dict:
    global _knn_db
    if _knn_db is not None:
        return _knn_db
    if DB_PATH.exists():
        try:
            with open(DB_PATH, 'rb') as f:
                _knn_db = pickle.load(f)
            return _knn_db
        except Exception:
            pass
    if TRAIN_DATA_DIR.exists():
        _knn_db = build_template_db(TRAIN_DATA_DIR)
        if _knn_db:
            with open(DB_PATH, 'wb') as f:
                pickle.dump(_knn_db, f)
    else:
        _knn_db = {}
    return _knn_db


def knn_classify(feat: np.ndarray, db: dict, k: int = KNN_K) -> tuple:
    if not db:
        return '?', 0.0
    distances = [(float(np.linalg.norm(feat - t)), ch)
                 for ch, templates in db.items() for t in templates]
    distances.sort(key=lambda x: x[0])
    top_k = distances[:k]
    votes = Counter(ch for _, ch in top_k)
    best, count = votes.most_common(1)[0]
    return best, count / k


# =====================================================================
# EASYOCR (last resort)
# =====================================================================

def get_reader():
    global _reader
    if _reader is None:
        _reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    return _reader


def easyocr_read(img_gray: np.ndarray) -> str:
    reader = get_reader()
    candidates = []
    for fx in [3, 4]:
        try:
            s = cv2.resize(img_gray, None, fx=fx, fy=fx, interpolation=cv2.INTER_CUBIC)
            _, t = cv2.threshold(s, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            results = reader.readtext(t,
                allowlist='abcdefghijklmnopqrstuvwxyz0123456789',
                detail=1, paragraph=False, min_size=5,
                text_threshold=0.4, low_text=0.3, width_ths=0.8)
            if results:
                text = ''.join(r[1].lower().strip()
                               for r in sorted(results, key=lambda r: r[0][0][0]))
                text = re.sub(r'[^a-z0-9]', '', text)
                for w, r in [('rn','m'),('ri','n'),('cl','d'),('vv','w')]:
                    text = text.replace(w, r)
                if text: candidates.append(text[:CAPTCHA_LENGTH])
        except Exception:
            continue
    if not candidates: return ''
    valid = [c for c in candidates if len(c) == CAPTCHA_LENGTH]
    pool = valid or candidates
    result = []
    for i in range(CAPTCHA_LENGTH):
        chars = [c[i] for c in pool if i < len(c)]
        result.append(Counter(chars).most_common(1)[0][0] if chars else '?')
    return ''.join(result)


# =====================================================================
# MAIN: SVM → KNN → EasyOCR
# =====================================================================

def read_captcha_from_gray(img_gray: np.ndarray) -> str:
    try:
        crops = find_char_boundaries(img_gray)
    except Exception:
        return easyocr_read(img_gray)

    svm = load_svm()
    db  = load_or_build_db() if not svm else {}  # KNN chỉ load khi không có SVM

    chars, low_conf = [], []

    for i, crop in enumerate(crops):
        if svm:
            ch, conf = svm_predict(crop)
            threshold = SVM_CONF_THRESHOLD
        elif db:
            feat = extract_features(crop)
            ch, conf = knn_classify(feat, db)
            threshold = KNN_CONF_THRESHOLD
        else:
            chars.append('?')
            low_conf.append(i)
            continue

        chars.append(ch)
        if conf < threshold:
            low_conf.append(i)

    if not low_conf:
        return ''.join(chars)

    # EasyOCR cho các vị trí confidence thấp
    ocr = easyocr_read(img_gray)
    final = list(chars)
    if len(ocr) == CAPTCHA_LENGTH:
        for pos in low_conf:
            final[pos] = ocr[pos]
    return ''.join(final)


def read_captcha_from_file(image_path: str) -> str:
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Cannot read: {image_path}")
    return read_captcha_from_gray(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))


def read_captcha_from_pil(pil_image: Image.Image) -> str:
    arr = np.array(pil_image.convert('RGB'))
    gray = cv2.cvtColor(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), cv2.COLOR_BGR2GRAY)
    return read_captcha_from_gray(gray)


def read_captcha_from_bytes(image_bytes: bytes) -> str:
    """Read CAPTCHA from image bytes"""
    import io
    pil_image = Image.open(io.BytesIO(image_bytes))
    return read_captcha_from_pil(pil_image)


def rebuild_db():
    global _knn_db
    if DB_PATH.exists(): DB_PATH.unlink()
    _knn_db = None
    return load_or_build_db()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == '--rebuild':
            rebuild_db()
        else:
            print(read_captcha_from_file(sys.argv[1]))
    else:
        print("Usage: python scan_code.py <image_path>")
        print("       python scan_code.py --rebuild")