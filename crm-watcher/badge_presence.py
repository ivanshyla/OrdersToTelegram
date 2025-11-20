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

def has_red_background(img_bgr, text_bbox):
    """Проверяет, есть ли КРАСНЫЙ ФОН вокруг текста (badge)"""
    x, y, w, h = text_bbox
    
    # Расширяем область вокруг текста чтобы захватить фон badge
    padding = max(5, int(h * 0.3))
    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(img_bgr.shape[1], x + w + padding)
    y2 = min(img_bgr.shape[0], y + h + padding)
    
    roi = img_bgr[y1:y2, x1:x2]
    
    # HSV маска для красного ФОНА
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([15, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([165, 80, 80]), np.array([180, 255, 255]))
    red_mask = m1 | m2
    
    # Процент красных пикселей в области вокруг текста
    red_ratio = np.sum(red_mask > 0) / max(1, red_mask.size)
    
    # Badge имеет красный фон, обычно >30% области красная
    return red_ratio > 0.25

def extract_card_numbers(img_bgr, date_bbox, debug=False):
    """
    ПРАВИЛЬНЫЙ подход: извлекает числа из карточки с датой.
    Читает "Кол-во заказов" и "Подтвержденные заказы".
    Если они не равны - есть неразобранные заказы.
    """
    if not date_bbox:
        return False, None, None, 0.0
    
    H, W = img_bgr.shape[:2]
    x, y, w, h = date_bbox
    
    # Расширяем область чтобы захватить всю карточку
    # Карточка находится ВЕРТИКАЛЬНО под датой
    # Используем ширину блока даты + немного больше для захвата всей карточки
    
    # Карточка должна быть примерно в 2.5 раза шире чем дата
    card_width = int(w * 2.8)
    
    # Начинаем от ЛЕВОГО края даты и идем вниз
    x1 = max(0, x)  # От левого края даты
    y1 = max(0, y)  # От верха даты
    x2 = min(W, x + card_width)  # Ширина пропорциональна дате
    y2 = min(H, y + 280)  # Высота карточки вниз от даты
    
    card_roi = img_bgr[y1:y2, x1:x2]
    
    # ПРЕДОБРАБОТКА для лучшего распознавания мелких чисел
    # Увеличиваем изображение в 2 раза
    card_roi_upscaled = cv2.resize(card_roi, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    
    # Улучшаем контраст (CLAHE)
    gray = cv2.cvtColor(card_roi_upscaled, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    enhanced = clahe.apply(gray)
    card_roi_enhanced = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
    
    # OCR на улучшенной карточке
    try:
        ocr_results = get_reader().readtext(card_roi_enhanced, detail=1, paragraph=False)
    except:
        return False, (x1, y1, x2-x1, y2-y1), None, 0.0
    
    # Ищем ВСЕ числа в карточке (любого размера)
    numbers_found = []
    
    for box, text, conf in ocr_results:
        # Ищем ЧИСЛА (двузначные и трехзначные)
        text_clean = re.sub(r'\s+', '', str(text))
        if not re.match(r'^\d{2,3}$', text_clean):
            continue
        
        number = int(text_clean)
        
        # Получаем позицию числа (учитываем что изображение увеличено в 2x)
        text_bbox = _bbox_from_quad(box)
        # Масштабируем обратно к оригинальному размеру
        text_bbox_orig = (
            text_bbox[0] // 2,
            text_bbox[1] // 2,
            text_bbox[2] // 2,
            text_bbox[3] // 2
        )
        abs_text_bbox = (
            x1 + text_bbox_orig[0],
            y1 + text_bbox_orig[1],
            text_bbox_orig[2],
            text_bbox_orig[3]
        )
        
        # Пропускаем очень маленькие числа (высота < 8px в оригинале)
        if text_bbox_orig[3] < 8:
            continue
        
        numbers_found.append({
            'value': number,
            'bbox': abs_text_bbox,
            'y_pos': abs_text_bbox[1],
            'x_pos': abs_text_bbox[0],
            'height': text_bbox_orig[3],
            'conf': conf
        })
    
    # Сортируем по вертикальной позиции (сверху вниз)
    numbers_found.sort(key=lambda n: n['y_pos'])
    
    # Теперь нужно найти два РАЗНЫХ числа
    # Первое - "Кол-во заказов" (черный блок, верх)
    # Второе - "Подтвержденные заказы" (зеленый блок, ниже)
    
    has_unprocessed = False
    total_orders = None
    confirmed_orders = None
    
    # Убираем дубликаты - берем уникальные значения
    unique_numbers = []
    seen_values = set()
    for num in numbers_found:
        if num['value'] not in seen_values:
            seen_values.add(num['value'])
            unique_numbers.append(num)
    
    if len(unique_numbers) >= 2:
        # Берем первые два разных числа сверху вниз
        total_orders = unique_numbers[0]['value']
        confirmed_orders = unique_numbers[1]['value']
    elif len(unique_numbers) == 1 and len(numbers_found) >= 2:
        # Если все числа одинаковые - значит все заказы подтверждены
        total_orders = unique_numbers[0]['value']
        confirmed_orders = unique_numbers[0]['value']
    
    if total_orders is not None and confirmed_orders is not None:
        
        # Если подтвержденных меньше чем всего - есть неразобранные
        has_unprocessed = (confirmed_orders < total_orders)
        
        if debug:
            dbg = img_bgr.copy()
            # Рамка даты
            cv2.rectangle(dbg, (x, y), (x+w, y+h), (255, 255, 0), 2)
            # Рамка карточки
            cv2.rectangle(dbg, (x1, y1), (x2, y2), (200, 200, 0), 2)
            # Маркируем найденные числа
            for i, num_info in enumerate(unique_numbers[:2]):
                bx, by, bw, bh = num_info['bbox']
                color = (0, 0, 255) if i == 0 else (0, 255, 0)  # Красный для total, зелёный для confirmed
                cv2.rectangle(dbg, (bx, by), (bx+bw, by+bh), color, 2)
                # Подписываем
                label = f"Total:{num_info['value']}" if i == 0 else f"Conf:{num_info['value']}"
                cv2.putText(dbg, label, (bx, by-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
            # Пишем результат
            result_text = f"Unprocessed: {has_unprocessed} ({total_orders-confirmed_orders} orders)" if has_unprocessed else "All OK"
            cv2.putText(dbg, result_text, (x1, y1-20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            
            return has_unprocessed, (x1, y1, x2-x1, y2-y1), dbg, 0.0
    
    return has_unprocessed, (x1, y1, x2-x1, y2-y1), None, 0.0

def detect_badge_presence_ocr(img_bgr, date_bbox, debug=False):
    """
    Проверяет наличие неразобранных заказов через сравнение чисел в карточке.
    Читает "Кол-во заказов" vs "Подтвержденные заказы".
    """
    return extract_card_numbers(img_bgr, date_bbox, debug)

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

