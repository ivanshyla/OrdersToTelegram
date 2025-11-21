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

def detect_red_badge_near_date(img_bgr, date_bbox, debug=False):
    """
    Ищем КРАСНЫЙ BADGE С ЦИФРОЙ рядом с датой.
    Это количество неразобранных заказов для КОНКРЕТНОЙ даты.
    """
    if not date_bbox:
        return False, None, None, 0.0
    
    H, W = img_bgr.shape[:2]
    x, y, w, h = date_bbox
    
    # Область поиска СПРАВА и СВЕРХУ от даты (где обычно badge)
    # Badge находится в правом верхнем углу карточки
    search_x1 = max(0, x + w - 20)  # Начинаем справа от даты
    search_y1 = max(0, y - 30)  # Чуть выше даты
    search_x2 = min(W, x + w + 80)  # Не слишком далеко вправо
    search_y2 = min(H, y + 50)  # Не слишком далеко вниз
    
    roi = img_bgr[search_y1:search_y2, search_x1:search_x2]
    
    # Ищем красный цвет (badge)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, np.array([0, 150, 150]), np.array([10, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([170, 150, 150]), np.array([180, 255, 255]))
    red_mask = m1 | m2
    
    # Находим контуры красных областей
    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    for contour in contours:
        area = cv2.contourArea(contour)
        # Badge компактный (300-3000 пикселей)
        if area < 300 or area > 3000:
            continue
        
        bx, by, bw, bh = cv2.boundingRect(contour)
        
        # Badge примерно квадратный или круглый
        aspect_ratio = bw / float(bh) if bh > 0 else 0
        if aspect_ratio < 0.7 or aspect_ratio > 1.5:
            continue
        
        # НАШЛИ красный badge!
        abs_bbox = (search_x1 + bx, search_y1 + by, bw, bh)
        
        if debug:
            dbg = img_bgr.copy()
            cv2.rectangle(dbg, (x, y), (x+w, y+h), (255, 255, 0), 2)  # Дата
            cv2.rectangle(dbg, (search_x1, search_y1), (search_x2, search_y2), (200, 200, 0), 1)  # ROI
            cv2.rectangle(dbg, (abs_bbox[0], abs_bbox[1]), 
                         (abs_bbox[0]+abs_bbox[2], abs_bbox[1]+abs_bbox[3]), (0, 0, 255), 3)  # Badge
            cv2.putText(dbg, "RED BADGE FOUND!", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            return True, abs_bbox, dbg, 0.0
        
        return True, abs_bbox, None, 0.0
    
    if debug:
        dbg = img_bgr.copy()
        cv2.rectangle(dbg, (x, y), (x+w, y+h), (255, 255, 0), 2)
        cv2.rectangle(dbg, (search_x1, search_y1), (search_x2, search_y2), (200, 200, 0), 1)
        cv2.putText(dbg, "NO BADGE", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        return False, None, dbg, 0.0
    
    return False, None, None, 0.0

def detect_badge_presence_ocr(img_bgr, date_bbox, debug=False):
    """
    Проверяет наличие КРАСНОГО BADGE рядом с датой.
    Badge показывает количество неразобранных заказов для КОНКРЕТНОЙ даты.
    """
    badge_found, badge_bbox, dbg_img, _ = detect_red_badge_near_date(img_bgr, date_bbox, debug)
    
    if badge_found:
        print(f"    🔴 НАЙДЕН КРАСНЫЙ BADGE рядом с датой - есть неразобранные заказы!")
    else:
        print(f"    ✅ Красного badge нет - все заказы разобраны")
    
    return badge_found, badge_bbox, dbg_img, 0.0

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
