"""
scan_code_svm_v7.py

Lịch sử:
  v4: 84.65% - top-2 margin, 0 regression ✓
  v5: 85.96% - thêm rules nhưng không trigger (margin quá nhỏ)
  v6: target ~87%+ - tăng margin
  v7: target ~90%+ - phân tích lỗi thực tế từ 303 ảnh test

Phát hiện từ report 20260306 (59 ảnh sai):
  n->h : 8x  ← LỖI LỚN NHẤT (rule cũ h->n chưa đủ, giờ thêm rule ngược)
  h->b : 3x
  5->b : 2x  (chưa có rule)
  5->s : 2x  (rule s->5 chưa trigger)
  r->n : 2x  (có rồi)
  r->d : 2x  (chưa có rule)
  h->k : 2x  (chưa có rule)
  n->r : 2x  (chưa có rule)
  w->e : 2x  (rule e->w chưa trigger)
  c->n : 2x  tổng (chưa có rule)
  5->6 : 1x, 6->h/r/f/a/e/8 nhiều loại → 6 hay bị nhầm

Thay đổi v7:
  - Giữ toàn bộ rules v6
  - Thêm: h->n margin nhỏ hơn để bắt lỗi n->h (8x)
  - Thêm: b->5 rule (5->b: 2x)
  - Thêm: d->r rule (r->d: 2x)
  - Thêm: k->h rule (h->k: 2x)
  - Thêm: r->n và n->r (bidirectional với margin khác nhau)
  - Thêm: n->c rule (c->n: 2x)
  - Tăng cường: e->w và s->5 (trigger chắc hơn)
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


# =====================================================================
# TOP-2 MARGIN RULES - v7
# Cú pháp: (predicted_char, preferred_char, margin_threshold)
# Nghĩa: nếu SVM predict ra `predicted_char`
#        nhưng `preferred_char` không kém quá `margin_threshold`
#        thì đổi sang `preferred_char`
# =====================================================================

TOP2_RULES = [
    # ── Từ v4/v6, đã hoạt động ──────────────────────────────────────
    ('r', 'n', 0.15),    # n->r: 2x

    # ── Tăng mạnh margin để chắc trigger ─────────────────────────────
    ('e', 'w', 0.35),    # w->e: 2x   (v6: 0.30 chưa đủ)
    ('s', '5', 0.35),    # 5->s: 2x   (v6: 0.30 chưa đủ)

    # ── Lỗi lớn nhất: n->h (8x) ──────────────────────────────────────
    # SVM predict 'h' nhưng thực ra là 'n'
    # Margin nhỏ hơn để bắt được nhiều hơn
    ('h', 'n', 0.15),    # n->h: 8x  (v6: 0.20 → giảm xuống 0.15)

    # ── Lỗi h->b (3x) ────────────────────────────────────────────────
    ('b', 'h', 0.25),    # h->b: 3x

    # ── Lỗi 5->b (2x) ────────────────────────────────────────────────
    ('b', '5', 0.30),    # 5->b: 2x  [MỚI]

    # ── Lỗi r->d (2x) ────────────────────────────────────────────────
    ('d', 'r', 0.25),    # r->d: 2x  [MỚI]

    # ── Lỗi h->k (2x) ────────────────────────────────────────────────
    ('k', 'h', 0.30),    # h->k: 2x  [MỚI]

    # ── Lỗi n->r (2x) ────────────────────────────────────────────────
    ('r', 'n', 0.20),    # n->r: 2x  [update margin]

    # ── Lỗi c->n (2x tổng: c->n và c->d) ────────────────────────────
    ('n', 'c', 0.25),    # c->n: 1x  [MỚI]

    # ── o vs 0 ───────────────────────────────────────────────────────
    ('0', 'o', 0.25),    # o->0: 1x  (từ v6)

    # ── Giữ phòng thủ ────────────────────────────────────────────────
    ('b', 'h', 0.20),    # h->b fallback
]

# Dedup: nếu có 2 rule cùng predicted_char thì giữ rule margin NHỎ HƠN (aggressive hơn)
def _dedup_rules(rules):
    seen = {}
    for top1, target, margin in rules:
        key = (top1, target)
        if key not in seen or margin < seen[key]:
            seen[key] = margin
    return [(k[0], k[1], v) for k, v in seen.items()]

TOP2_RULES = _dedup_rules(TOP2_RULES)


def apply_top2_fix(char: str, proba: np.ndarray, classes: list) -> str:
    class_to_idx = {c: i for i, c in enumerate(classes)}
    for top1_char, target_char, margin_thresh in TOP2_RULES:
        if char != top1_char:
            continue
        if target_char not in class_to_idx:
            continue
        prob_top1 = proba[class_to_idx[top1_char]]
        prob_target = proba[class_to_idx[target_char]]
        if prob_top1 - prob_target < margin_thresh:
            return target_char
    return char


# =====================================================================
# SVM
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
    model = load_svm()
    if model is None:
        return '?', 0.0
    feat = extract_features(crop).reshape(1, -1)
    proba = model.predict_proba(feat)[0]
    classes = list(model.classes_)
    top1_idx = int(np.argmax(proba))
    char = classes[top1_idx]
    conf = float(proba[top1_idx])
    fixed = apply_top2_fix(char, proba, classes)
    if fixed != char:
        conf = float(proba[classes.index(fixed)])
        char = fixed
    return char, conf


# =====================================================================
# KNN (fallback)
# =====================================================================

def build_template_db(train_dir: Path = TRAIN_DATA_DIR) -> dict:
    db = {}
    img_files = sorted(train_dir.glob('*.png'))
    if not img_files:
        return db
    print(f"[KNN] Building DB from {len(img_files)} images...")
    for img_path in img_files:
        label = img_path.stem
        if len(label) != CAPTCHA_LENGTH:
            continue
        img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        try:
            crops = find_char_boundaries(img)
            for ch, crop in zip(label, crops):
                if ch not in db:
                    db[ch] = []
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
# EASYOCR
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
                for w, r in [('rn', 'm'), ('ri', 'n'), ('cl', 'd'), ('vv', 'w')]:
                    text = text.replace(w, r)
                if text:
                    candidates.append(text[:CAPTCHA_LENGTH])
        except Exception:
            continue
    if not candidates:
        return ''
    valid = [c for c in candidates if len(c) == CAPTCHA_LENGTH]
    pool = valid or candidates
    result = []
    for i in range(CAPTCHA_LENGTH):
        chars = [c[i] for c in pool if i < len(c)]
        result.append(Counter(chars).most_common(1)[0][0] if chars else '?')
    return ''.join(result)


# =====================================================================
# MAIN
# =====================================================================

def read_captcha_from_gray(img_gray: np.ndarray) -> str:
    try:
        crops = find_char_boundaries(img_gray)
    except Exception:
        return easyocr_read(img_gray)

    svm = load_svm()
    db = load_or_build_db() if not svm else {}

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
    import io
    pil_image = Image.open(io.BytesIO(image_bytes))
    return read_captcha_from_pil(pil_image)


def rebuild_db():
    global _knn_db
    if DB_PATH.exists():
        DB_PATH.unlink()
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
        print("Usage: python scan_code_svm_v7.py <image_path>")
        print("       python scan_code_svm_v7.py --rebuild")