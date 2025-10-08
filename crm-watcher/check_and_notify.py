import os, asyncio, json, datetime as dt
from pathlib import Path
import cv2, requests
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from badge_presence import find_date_bbox, target_date_str, detect_badge_presence, red_mask_union

load_dotenv()
CRM_URL       = os.getenv("CRM_URL", "https://crm.clean-whale.com/login")
CRM_DASHBOARD = os.getenv("CRM_DASHBOARD", "https://crm.clean-whale.com/warsaw")
LOGIN         = os.getenv("CRM_LOGIN")
PASSWORD      = os.getenv("CRM_PASSWORD")
TG_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID")

ROOT = Path(__file__).parent
ART  = ROOT / "run_artifacts"; ART.mkdir(exist_ok=True)

async def ensure_dashboard(page):
    if "login" in page.url:
        # заполняем и жмём "Войти"
        for sel in ['input[name="email"]','input[type="email"]','input[id*="email" i]','input[name*="login" i]']:
            try: await page.fill(sel, LOGIN, timeout=1500); break
            except: pass
        for sel in ['input[name="password"]','input[type="password"]','input[id*="pass" i]']:
            try: await page.fill(sel, PASSWORD, timeout=1500); break
            except: pass
        for sel in ['button:has-text("Войти")','button[type="submit"]','text=/^Войти$/i']:
            try: await page.click(sel, timeout=1500); break
            except: pass
        await page.wait_for_load_state("networkidle", timeout=30000)
    await page.goto(CRM_DASHBOARD, wait_until="networkidle", timeout=35000)

async def grab_screenshot():
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_png = ART / f"dash_{ts}.png"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx = await browser.new_context(viewport={"width":1440,"height":900}, locale="ru-RU", timezone_id="Europe/Warsaw")
        page = await ctx.new_page()
        try:
            await page.goto(CRM_URL, wait_until="domcontentloaded", timeout=30000)
            await ensure_dashboard(page)
            await page.screenshot(path=str(out_png), full_page=True)
        finally:
            await ctx.close(); await browser.close()
    return str(out_png)

def check_badge_presence(png_path):
    img = cv2.imread(png_path)
    if img is None: raise RuntimeError(f"PNG not read: {png_path}")
    # ищем «завтра» (якорь) и проверяем «красное справа» — без цифр
    date_text = target_date_str("tomorrow")
    date_box  = find_date_bbox(img, date_text)
    present, roi, dbg, red_ratio = detect_badge_presence(img, date_box, debug=True)
    # сохраним на всякий случай маску/отладку рядом со скрином
    if roi:
        rx,ry,rw,rh = roi
        cv2.imwrite(png_path.replace(".png","_mask.png"), red_mask_union(img[ry:ry+rh, rx:rx+rw]))
    if dbg is not None:
        cv2.imwrite(png_path.replace(".png","_dbg.png"), dbg)
    return present, date_text, png_path

def send_photo_with_caption(image_path, caption):
    if not (TG_TOKEN and TG_CHAT_ID):
        print("WARN: no TELEGRAM_BOT_TOKEN/CHAT_ID — skip")
        return False
    with open(image_path, "rb") as f:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
            data={"chat_id": TG_CHAT_ID, "caption": caption},
            files={"photo": f},
            timeout=30,
        )
    ok = r.ok and r.json().get("ok", False)
    if not ok: print("Telegram error:", r.text)
    return ok

async def main():
    png = await grab_screenshot()
    present, date_text, png_path = check_badge_presence(png)
    if present:
        caption = f"⚠️ На {date_text} есть красная отметка (первый квадрат). Проверьте неразобранные заказы."
        sent = send_photo_with_caption(png_path, caption)
        print("RESULT:", {"present": True, "sent": sent, "date": date_text, "png": png_path})
    else:
        print("RESULT:", {"present": False, "date": date_text, "png": png_path})

if __name__ == "__main__":
    asyncio.run(main())
