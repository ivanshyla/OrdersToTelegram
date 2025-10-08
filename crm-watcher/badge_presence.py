import cv2, numpy as np, re, argparse, datetime as dt
import easyocr

reader = easyocr.Reader(["ru","en"], gpu=False, verbose=False)

from zoneinfo import ZoneInfo

def target_date_str(which):
    now = dt.datetime.now(ZoneInfo("Europe/Warsaw"))
    d = now.date() + dt.timedelta(days=1 if which=="tomorrow" else 0)
    # Возвращаем формат без ведущих нулей (как на сайте)
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

def red_mask_union(img_bgr):
    H,W = img_bgr.shape[:2]
    # HSV маска (широкая)
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, np.array([  0, 15, 50]), np.array([28,255,255]))
    m2 = cv2.inRange(hsv, np.array([160, 15, 50]), np.array([179,255,255]))
    
    # ИСКЛЮЧАЕМ синие оттенки (значок скидки)
    # Синий в HSV: примерно 90-130 градусов
    blue_mask = cv2.inRange(hsv, np.array([90, 40, 40]), np.array([130, 255, 255]))
    
    # RGB критерий - красный должен быть больше синего и зеленого
    b,g,r = cv2.split(img_bgr)
    rgb = ((r.astype(np.int16)-g.astype(np.int16) > 12) &
           (r.astype(np.int16)-b.astype(np.int16) > 12) &
           (r > 90)).astype(np.uint8)*255
    
    # LAB: красное = высокий a*
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    L,A,B = cv2.split(lab)
    # адаптивный порог по a*: базовый 145, либо (mean+0.8*std), что больше
    thr = max(145, int(np.mean(A) + 0.8*np.std(A)))
    lab_mask = (A >= thr).astype(np.uint8)*255

    # Объединяем красные маски
    mask = m1 | m2 | rgb | lab_mask
    
    # ИСКЛЮЧАЕМ синий цвет из финальной маски
    mask = cv2.bitwise_and(mask, cv2.bitwise_not(blue_mask))
    
    mask = cv2.medianBlur(mask, 3)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,9)), iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7)), iterations=1)
    return mask

def detect_badge_presence(img_bgr, date_bbox, debug=False):
    if not date_bbox:
        return False, None, None, 0.0
    H,W = img_bgr.shape[:2]
    x,y,w,h = date_bbox

    # ШИРОКАЯ полоса строки даты: справа от даты до правого края
    y1 = max(0, int(y - 2.5*h))
    y2 = min(H, int(y + 4.0*h))
    x1 = max(0, int(x + 0.1*w))
    x2 = W

    roi = img_bgr[y1:y2, x1:x2]
    mask = red_mask_union(roi)

    # доля красного в полосе (для отладки)
    red_ratio = float((mask>0).sum()) / max(1, mask.size)

    # находим компоненты и проверяем «достаточно крупную» рядом с датой
    cnts,_ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = max(100, int(0.12*h*h))  # минимальная площадь - делаем более чувствительным
    
    present = False
    best = None
    best_score = None
    
    for c in cnts:
        rx,ry,rw,rh = cv2.boundingRect(c)
        area = rw*rh
        aspect = rw/max(1,rh)
        
        if area < min_area: 
            continue
        if not (0.3 <= aspect <= 6.0):  # широкий диапазон пропорций
            continue
            
        # проверяем что компонент справа от даты
        comp_center_x = x1 + rx + rw/2
        date_right = x + w
        dist_x = comp_center_x - date_right
        
        # Должен быть справа от даты и в разумных пределах
        if dist_x < 0 or dist_x > w*4:
            continue
        
        # приоритет ближайшему крупному компоненту
        score = (dist_x, -area)
        if (not best) or score < best_score:
            best = (score, (rx,ry,rw,rh))
            best_score = score
            present = True

    if debug:
        dbg = img_bgr.copy()
        # рамка даты
        cv2.rectangle(dbg,(x,y),(x+w,y+h),(255,255,0),2)
        # ROI
        cv2.rectangle(dbg,(x1,y1),(x2,y2),(200,200,0),1)
        # лучшая компонента
        if best:
            rx,ry,rw,rh = best[1]
            cv2.rectangle(dbg,(x1+rx,y1+ry),(x1+rx+rw,y1+ry+rh),(0,0,255),3)
        return present, (x1,y1,x2-x1,y2-y1), dbg, red_ratio

    return present, (x1,y1,x2-x1,y2-y1), None, red_ratio

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image",  default="debug/03_after_submit.png")
    ap.add_argument("--target", default="tomorrow", choices=["today","tomorrow"])
    ap.add_argument("--out",    default="debug/presence_debug.png")
    ap.add_argument("--mask",   default="debug/presence_mask.png")
    args = ap.parse_args()

    img = cv2.imread(args.image)
    if img is None: raise SystemExit(f"no image at {args.image}")

    date_txt = target_date_str(args.target)
    date_box = find_date_bbox(img, date_txt)
    present, roi, dbg, red_ratio = detect_badge_presence(img, date_box, debug=True)

    if roi:
        rx,ry,rw,rh = roi
        cv2.imwrite(args.mask, red_mask_union(img[ry:ry+rh, rx:rx+rw]))
    if dbg is not None:
        cv2.imwrite(args.out, dbg)

    print(f"date={date_txt} date_found={bool(date_box)} badge_present={present} red_ratio={red_ratio:.4f}")
if __name__ == "__main__":
    main()
