import cv2, numpy as np, re, argparse, datetime as dt
import easyocr

reader = easyocr.Reader(["ru","en"], gpu=False, verbose=False)

from zoneinfo import ZoneInfo

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
    res = reader.readtext(img_bgr, detail=1, paragraph=False)
    wanted = re.sub(r"\s+","", date_text)
    best=None; best_conf=0.0
    for box,text,conf in res:
        if wanted in re.sub(r"\s+","", str(text)) and conf>best_conf:
            best=_bbox_from_quad(box); best_conf=conf
    return best

def has_red_background(img_bgr, text_bbox):
    """Проверяет, есть ли КРАСНЫЙ или ОРАНЖЕВЫЙ ФОН вокруг текста (badge)"""
    x, y, w, h = text_bbox
    
    # Расширяем область вокруг текста чтобы захватить фон badge
    padding = max(5, int(h * 0.3))
    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(img_bgr.shape[1], x + w + padding)
    y2 = min(img_bgr.shape[0], y + h + padding)
    
    roi = img_bgr[y1:y2, x1:x2]
    
    # HSV маска для КРАСНОГО и ОРАНЖЕВОГО фона
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    # Красный: 0-15 и 165-180
    m1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([15, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([165, 80, 80]), np.array([180, 255, 255]))
    # ОРАНЖЕВЫЙ: 10-25 (между красным и желтым)
    m3 = cv2.inRange(hsv, np.array([10, 100, 100]), np.array([25, 255, 255]))
    
    red_orange_mask = m1 | m2 | m3
    
    # Процент красно-оранжевых пикселей в области вокруг текста
    red_orange_ratio = np.sum(red_orange_mask > 0) / max(1, red_orange_mask.size)
    
    # Badge имеет красный/оранжевый фон, обычно >25% области
    return red_orange_ratio > 0.20

def detect_badge_presence_ocr(img_bgr, date_bbox, debug=False):
    """
    Новый подход: ищем ЦИФРЫ в красном тексте рядом с датой
    Badge всегда содержит число (количество заказов)
    """
    if not date_bbox:
        return False, None, None, 0.0
    
    H, W = img_bgr.shape[:2]
    x, y, w, h = date_bbox
    
    # Область поиска справа от даты (умеренная)
    y1 = max(0, int(y - 1.0*h))
    y2 = min(H, int(y + 2.0*h))
    x1 = int(x + w)  # начинаем сразу после даты
    x2 = min(W, int(x + w + w*8))  # не слишком далеко
    
    roi = img_bgr[y1:y2, x1:x2]
    
    # OCR в области справа от даты
    try:
        ocr_results = reader.readtext(roi, detail=1, paragraph=False)
    except:
        return False, (x1, y1, x2-x1, y2-y1), None, 0.0
    
    # Ищем ЦИФРЫ в красном тексте
    badge_found = False
    best_badge = None
    best_distance = float('inf')
    
    for box, text, conf in ocr_results:
        # Проверяем что это цифра
        text_clean = re.sub(r'\s+', '', str(text))
        if not re.match(r'^\d+$', text_clean):
            continue
        
        # Получаем bbox текста
        text_bbox = _bbox_from_quad(box)
        abs_text_bbox = (
            x1 + text_bbox[0],
            y1 + text_bbox[1],
            text_bbox[2],
            text_bbox[3]
        )
        
        # Проверяем что у текста КРАСНЫЙ ФОН (badge)
        if not has_red_background(img_bgr, abs_text_bbox):
            continue
        
        # Это badge! Цифра на красном фоне
        # Проверяем расстояние от даты (берем ближайший)
        text_center_x = abs_text_bbox[0] + abs_text_bbox[2]/2
        date_right = x + w
        distance = abs(text_center_x - date_right)
        
        if distance < best_distance:
            badge_found = True
            best_badge = abs_text_bbox
            best_distance = distance
    
    if debug and badge_found:
        dbg = img_bgr.copy()
        # Рамка даты
        cv2.rectangle(dbg, (x, y), (x+w, y+h), (255, 255, 0), 2)
        # ROI
        cv2.rectangle(dbg, (x1, y1), (x2, y2), (200, 200, 0), 1)
        # Badge
        if best_badge:
            bx, by, bw, bh = best_badge
            cv2.rectangle(dbg, (bx, by), (bx+bw, by+bh), (0, 0, 255), 3)
        return badge_found, (x1, y1, x2-x1, y2-y1), dbg, 0.0
    
    return badge_found, (x1, y1, x2-x1, y2-y1), None, 0.0

def red_mask_union(img_bgr):
    """Создает маску красных пикселей для отладки"""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([15, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([165, 80, 80]), np.array([180, 255, 255]))
    return m1 | m2

# Обратная совместимость - старое название функции
def detect_badge_presence(img_bgr, date_bbox, debug=False):
    return detect_badge_presence_ocr(img_bgr, date_bbox, debug)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="debug/03_after_submit.png")
    ap.add_argument("--target", default="tomorrow", choices=["today","tomorrow"])
    ap.add_argument("--out", default="debug/presence_debug_ocr.png")
    args = ap.parse_args()

    img = cv2.imread(args.image)
    if img is None:
        raise SystemExit(f"no image at {args.image}")

    date_txt = target_date_str(args.target)
    date_box = find_date_bbox(img, date_txt)
    present, roi, dbg, _ = detect_badge_presence_ocr(img, date_box, debug=True)

    if dbg is not None:
        cv2.imwrite(args.out, dbg)

    print(f"date={date_txt} date_found={bool(date_box)} badge_present={present}")
    print(f"Method: OCR-based (searching for RED NUMBERS)")

if __name__ == "__main__":
    main()

