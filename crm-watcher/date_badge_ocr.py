import cv2, numpy as np, re, argparse, datetime as dt
import easyocr

reader = easyocr.Reader(["ru","en"], gpu=False, verbose=False)

def target_date_str(which):
    d = dt.date.today() + dt.timedelta(days=1 if which=="tomorrow" else 0)
    return d.strftime("%d.%m")

def _bbox_from_quad(quad):
    xs=[p[0] for p in quad]; ys=[p[1] for p in quad]
    x1,y1,x2,y2=min(xs),min(ys),max(xs),max(ys)
    return int(x1),int(y1),int(x2-x1),int(y2-y1)

def find_date_bbox(img_bgr, date_text):
    results = reader.readtext(img_bgr, detail=1, paragraph=False)
    wanted = re.sub(r"\s+","", date_text)
    best=None; best_conf=0
    for box,text,conf in results:
        if wanted in re.sub(r"\s+","", text) and conf>best_conf:
            best=_bbox_from_quad(box); best_conf=conf
    return best

def build_masks(img_bgr):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    # красный (вкл. оранжево-красный)
    m1 = cv2.inRange(hsv, np.array([  0, 40, 70]), np.array([28,255,255]))
    m2 = cv2.inRange(hsv, np.array([160, 40, 70]), np.array([179,255,255]))
    red = cv2.morphologyEx(m1|m2, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,9)), iterations=2)
    red = cv2.morphologyEx(red, cv2.MORPH_OPEN,  cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7)), iterations=1)

    # белый текст (низкая насыщенность, высокая яркость)
    s = hsv[:,:,1]; v = hsv[:,:,2]
    white = ((s < 60) & (v > 200)).astype(np.uint8)*255
    white = cv2.morphologyEx(white, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT,(3,3)), iterations=1)
    return red, white

def find_red_components(img_bgr):
    red, _ = build_masks(img_bgr)
    contours,_ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    H,W = img_bgr.shape[:2]
    boxes=[]
    for c in contours:
        x,y,w,h = cv2.boundingRect(c)
        area=w*h; aspect=w/max(1,h)
        if 0.00008*W*H < area < 0.03*W*H and 0.4 < aspect < 5.5:
            boxes.append((x,y,w,h))
    return boxes, red

def choose_badge_right_of_date(img_bgr, date_bbox, boxes):
    """берём ближайший красный бокс СПРАВА от даты, с достаточной долей белого внутри"""
    if not date_bbox: return None, 0
    red_mask, white_mask = build_masks(img_bgr)
    x,y,w,h = date_bbox
    cx, cy = x + w/2, y + h/2
    H,W = img_bgr.shape[:2]

    candidates = []
    for (rx,ry,rw,rh) in boxes:
        rcx, rcy = rx + rw/2, ry + rh/2
        dx, dy = rcx - cx, rcy - cy
        if dx < -10:           # только справа
            continue
        if not (y - 2.5*h <= rcy <= y + 3.5*h):   # вертикальная полоса вокруг даты
            continue
        if not (0.3*h <= rh <= 3.5*h):            # разумный размер
            continue
        # доля "белого" внутри красного компонента
        pad = max(3, int(0.15*min(rw,rh)))
        x1,y1 = max(0, rx+pad), max(0, ry+pad)
        x2,y2 = min(W, rx+rw-pad), min(H, ry+rh-pad)
        if x2 <= x1 or y2 <= y1: 
            continue
        red_roi   = red_mask[y1:y2, x1:x2]
        white_roi = white_mask[y1:y2, x1:x2]
        red_area = max(1, int((red_roi>0).sum()))
        white_on_red = int(((white_roi>0) & (red_roi>0)).sum())
        white_ratio = white_on_red / red_area
        if white_ratio < 0.05:            # есть белые цифры
            continue
        score = (abs(dx), abs(dy))        # ближе по X, затем по |Y|
        candidates.append(((rx,ry,rw,rh), score))

    candidates.sort(key=lambda z: z[1])
    return (candidates[0][0] if candidates else None), len(candidates)

def ocr_digits(img_bgr, box, pad_ratio=0.12):
    x,y,w,h = box
    pad = max(2, int(pad_ratio*min(w,h)))
    x1,y1 = max(0,x-pad), max(0,y-pad)
    x2,y2 = min(img_bgr.shape[1],x+w+pad), min(img_bgr.shape[0],y+h+pad)
    crop = img_bgr[y1:y2, x1:x2]
    # увеличим для OCR
    scale = 2
    crop = cv2.resize(crop, (crop.shape[1]*scale, crop.shape[0]*scale), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _,thr = cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    text = "".join(reader.readtext(thr, detail=0))
    m = re.findall(r"\d{1,2}", text)
    return (m[0] if m else ""), crop

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image",  default="debug/03_after_submit.png")
    ap.add_argument("--target", default="tomorrow", choices=["today","tomorrow"])
    ap.add_argument("--out",    default="debug/ocr_debug.png")
    ap.add_argument("--mask",   default="debug/red_mask.png")
    args = ap.parse_args()

    img = cv2.imread(args.image)
    if img is None: raise SystemExit(f"no image at {args.image}")

    date = target_date_str(args.target)
    date_bbox = find_date_bbox(img, date)
    boxes, red = find_red_components(img)
    cv2.imwrite(args.mask, red)

    chosen, cand_cnt = choose_badge_right_of_date(img, date_bbox, boxes)
    num = ""
    if chosen: num,_ = ocr_digits(img, chosen, pad_ratio=0.12)

    print(f"date={date} date_found={bool(date_bbox)} candidates={cand_cnt} badge_found={bool(chosen)} number={num or 'N/A'}")

    # визуализация
    dbg = img.copy()
    if date_bbox:
        x,y,w,h = date_bbox; cv2.rectangle(dbg,(x,y),(x+w,y+h),(255,255,0),2)
    for (rx,ry,rw,rh) in boxes:
        cv2.rectangle(dbg,(rx,ry),(rx+rw,ry+rh),(0,255,0),1)
    if chosen:
        rx,ry,rw,rh = chosen; cv2.rectangle(dbg,(rx,ry),(rx+rw,ry+rh),(0,0,255),3)
    cv2.imwrite(args.out, dbg)

if __name__ == "__main__":
    main()
