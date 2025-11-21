import cv2, numpy as np, re, argparse, datetime as dt
import easyocr

from zoneinfo import ZoneInfo

# Lazy initialization of OCR reader
_reader = None

def get_reader():
    """Lazy initialization of EasyOCR reader to avoid downloading models on import"""
    global _reader
    if _reader is None:
        _reader = easyocr.Reader(["ru","en"], gpu=False, verbose=False)
    return _reader

def target_date_str(which, timezone="Europe/Warsaw"):
    """Возвращает строку даты в формате DD.MM для указанного часового пояса"""
    now = dt.datetime.now(ZoneInfo(timezone))
    d = now.date() + dt.timedelta(days=1 if which=="tomorrow" else 0)
    # Возвращаем формат без ведущих нулей для дня (как на сайте)
    return f"{d.day}.{d.month:02d}"

def _bbox_from_quad(quad):
    xs=[p[0] for p in quad]; ys=[p[1] for p in quad]
    x1,y1,x2,y2=min(xs),min(ys),max(xs),max(ys)
    return int(x1),int(y1),int(x2-x1),int(y2-y1)

def find_date_bbox(img_bgr, date_text):
    res = get_reader().readtext(img_bgr, detail=1, paragraph=False)
    wanted = re.sub(r"\s+","", date_text)
    best=None; best_conf=0.0
    for box,text,conf in res:
        if wanted in re.sub(r"\s+","", str(text)) and conf>best_conf:
            best=_bbox_from_quad(box); best_conf=conf
    return best

def detect_yellow_warning(img_bgr, debug=False):
    """
    Ищем ЖЕЛТОЕ ПРЕДУПРЕЖДЕНИЕ "Есть незавершенные заказы"
    Это и есть те самые "неразобранные заказы"!
    """
    H, W = img_bgr.shape[:2]
    
    # Ищем желтый блок предупреждения
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    
    # Маска для желтого цвета
    yellow_mask = cv2.inRange(hsv, np.array([20, 100, 100]), np.array([35, 255, 255]))
    
    # Находим контуры
    contours, _ = cv2.findContours(yellow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    for contour in contours:
        area = cv2.contourArea(contour)
        # Предупреждение - это большой блок
        if area < 5000:
            continue
        
        x, y, w, h = cv2.boundingRect(contour)
        
        # Проверяем что это широкий блок (предупреждение)
        if w < 200 or h < 30:
            continue
        
        aspect_ratio = w / float(h)
        if aspect_ratio < 3:  # Предупреждение широкое
            continue
        
        # НАШЛИ желтое предупреждение!
        if debug:
            dbg = img_bgr.copy()
            cv2.rectangle(dbg, (x, y), (x+w, y+h), (0, 255, 255), 3)
            cv2.putText(dbg, "NEZAVERSHENNYYE!", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
            return True, (x, y, w, h), dbg
        
        return True, (x, y, w, h), None
    
    if debug:
        return False, None, img_bgr.copy()
    
    return False, None, None

def detect_badge_presence_ocr(img_bgr, date_bbox, debug=False):
    """
    Проверяет наличие НЕЗАВЕРШЕННЫХ (неразобранных) заказов.
    Ищет желтое предупреждение на экране.
    """
    warning_found, warning_bbox, dbg_img = detect_yellow_warning(img_bgr, debug)
    
    if warning_found:
        print(f"    ⚠️  НАЙДЕНО ЖЕЛТОЕ ПРЕДУПРЕЖДЕНИЕ - есть незавершенные заказы!")
    else:
        print(f"    ✅ Желтого предупреждения нет - все заказы разобраны")
    
    return warning_found, warning_bbox, dbg_img, 0.0

# Обратная совместимость
def detect_badge_presence(img_bgr, date_bbox, debug=False):
    return detect_badge_presence_ocr(img_bgr, date_bbox, debug)

def red_mask_union(img_bgr):
    """Создает маску красных пикселей для отладки"""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([15, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([165, 80, 80]), np.array([180, 255, 255]))
    return m1 | m2

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="debug/03_after_submit.png")
    ap.add_argument("--target", default="tomorrow", choices=["today","tomorrow"])
    ap.add_argument("--out", default="debug/presence_debug.png")
    args = ap.parse_args()

    img = cv2.imread(args.image)
    if img is None:
        raise SystemExit(f"no image at {args.image}")

    date_txt = target_date_str(args.target)
    date_box = find_date_bbox(img, date_txt)
    present, roi, dbg, _ = detect_badge_presence_ocr(img, date_box, debug=True)

    if dbg is not None:
        cv2.imwrite(args.out, dbg)

    print(f"date={date_txt} date_found={bool(date_box)} yellow_warning={present}")
    print(f"Method: Yellow warning detection")

if __name__ == "__main__":
    main()
