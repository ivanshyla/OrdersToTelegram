#!/usr/bin/env python3
"""
Мониторинг нескольких CRM систем одновременно
"""

import os, asyncio, json, datetime as dt
from pathlib import Path
import cv2, requests
from playwright.async_api import async_playwright
from zoneinfo import ZoneInfo

from badge_presence import find_date_bbox, target_date_str, detect_badge_presence, red_mask_union
from multi_crm_config import CRM_CONFIGS, TELEGRAM_BOT_TOKEN

ROOT = Path(__file__).parent
ART = ROOT / "run_artifacts"
ART.mkdir(exist_ok=True)

class CRMMonitor:
    def __init__(self, city_key, config):
        self.city_key = city_key
        self.config = config
        self.name = config["name"]
        
    async def ensure_dashboard(self, page):
        """Авторизация и переход на дашборд"""
        print(f"[{self.name}] Current URL: {page.url}")
        
        if "login" in page.url:
            print(f"[{self.name}] Login page detected, attempting authentication...")
            
            # Заполняем логин
            login_filled = False
            for sel in ['input[name="email"]','input[type="email"]','input[id*="email" i]','input[name*="login" i]']:
                try: 
                    await page.fill(sel, self.config["login"], timeout=1500)
                    print(f"[{self.name}] Login filled with selector: {sel}")
                    login_filled = True
                    break
                except Exception as e: 
                    print(f"[{self.name}] Failed to fill login with {sel}: {e}")
            
            # Заполняем пароль
            password_filled = False
            for sel in ['input[name="password"]','input[type="password"]','input[id*="pass" i]']:
                try: 
                    await page.fill(sel, self.config["password"], timeout=1500)
                    print(f"[{self.name}] Password filled with selector: {sel}")
                    password_filled = True
                    break
                except Exception as e:
                    print(f"[{self.name}] Failed to fill password with {sel}: {e}")
            
            if not (login_filled and password_filled):
                print(f"[{self.name}] WARNING: Failed to fill login/password fields")
            
            # Жмём кнопку входа
            login_clicked = False
            selectors_to_try = [
                'button:has-text("Войти")',
                'button[type="submit"]', 
                'text=/^Войти$/i',
                'input[type="submit"]',
                'button:has-text("Sign in")',
                'button:has-text("Login")',
                '[role="button"]:has-text("Войти")',
                'form button'
            ]
            
            for sel in selectors_to_try:
                try: 
                    await page.click(sel, timeout=1500)
                    print(f"[{self.name}] Login button clicked with selector: {sel}")
                    login_clicked = True
                    await page.wait_for_timeout(2000)
                    break
                except Exception as e:
                    print(f"[{self.name}] Failed to click login with {sel}: {e}")
            
            if not login_clicked:
                print(f"[{self.name}] WARNING: Failed to click login button - trying Enter key")
                try:
                    await page.keyboard.press("Enter")
                    login_clicked = True
                    await page.wait_for_timeout(2000)
                except Exception as e:
                    print(f"[{self.name}] Enter key also failed: {e}")
                
            # Ждём редиректа после логина
            try:
                await page.wait_for_url(lambda url: "login" not in url, timeout=30000)
                print(f"[{self.name}] Login successful! Redirected to: {page.url}")
            except Exception as e:
                print(f"[{self.name}] Login might have failed, still on login page: {e}")
                await page.wait_for_load_state("networkidle", timeout=10000)
                print(f"[{self.name}] After login URL: {page.url}")
        
        # Переходим на дашборд только если не уже там
        if page.url != self.config["crm_dashboard"]:
            print(f"[{self.name}] Navigating to dashboard: {self.config['crm_dashboard']}")
            try:
                await page.goto(self.config["crm_dashboard"], wait_until="networkidle", timeout=35000)
                print(f"[{self.name}] Dashboard loaded successfully: {page.url}")
            except Exception as e:
                print(f"[{self.name}] Failed to load dashboard with networkidle: {e}")
                try:
                    await page.goto(self.config["crm_dashboard"], wait_until="domcontentloaded", timeout=15000)
                    print(f"[{self.name}] Dashboard loaded with domcontentloaded: {page.url}")
                except Exception as e2:
                    print(f"[{self.name}] Dashboard loading completely failed: {e2}")
                    raise e2
        else:
            print(f"[{self.name}] Already on dashboard!")
        
        # Ждем загрузки календаря с датами на дашборде
        print(f"[{self.name}] Waiting for calendar dates to load...")
        try:
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(2000)
            await page.wait_for_selector('text=/\\d{1,2}\\.\\d{2}/', timeout=15000)
            print(f"[{self.name}] Calendar dates found on page")
            await page.wait_for_timeout(3000)
        except Exception as e:
            print(f"[{self.name}] Warning: Could not find calendar dates: {e}")
            await page.wait_for_timeout(5000)

    async def grab_screenshot(self):
        """Делает скриншот CRM дашборда"""
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_png = ART / f"dash_{self.city_key}_{ts}.png"
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
            ctx = await browser.new_context(viewport={"width":1440,"height":900}, locale="ru-RU", timezone_id=self.config["timezone"])
            page = await ctx.new_page()
            try:
                await page.goto(self.config["crm_url"], wait_until="domcontentloaded", timeout=30000)
                await self.ensure_dashboard(page)
                
                # Делаем скриншот только верхней части с календарем
                await page.screenshot(
                    path=str(out_png), 
                    full_page=False,
                    clip={'x': 0, 'y': 0, 'width': 1440, 'height': 800}
                )
                print(f"[{self.name}] Screenshot saved: {out_png}")
            finally:
                await ctx.close()
                await browser.close()
        return str(out_png)

    def check_badge_presence(self, png_path):
        """Проверяет наличие неразобранных заказов"""
        img = cv2.imread(png_path)
        if img is None: 
            raise RuntimeError(f"PNG not read: {png_path}")
        
        # Определяем какую дату проверять в зависимости от времени
        city_time = dt.datetime.now(ZoneInfo(self.config["timezone"]))
        current_hour = city_time.hour
        
        # Утром (7:30) проверяем СЕГОДНЯ, вечером (19-21) проверяем ЗАВТРА
        if current_hour < 12:  # До полудня - проверяем сегодня
            date_text = target_date_str("today")
        else:  # После полудня - проверяем завтра
            date_text = target_date_str("tomorrow")
        
        date_box = find_date_bbox(img, date_text)
        present, roi, dbg, red_ratio = detect_badge_presence(img, date_box, debug=True)
        
        # Сохраняем отладочные изображения
        if roi:
            rx,ry,rw,rh = roi
            cv2.imwrite(png_path.replace(".png", f"_{self.city_key}_mask.png"), red_mask_union(img[ry:ry+rh, rx:rx+rw]))
        if dbg is not None:
            cv2.imwrite(png_path.replace(".png", f"_{self.city_key}_dbg.png"), dbg)
        
        return present, date_text, png_path

    def resize_for_telegram(self, image_path):
        """Изменяет размер изображения для Telegram"""
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")
        
        h, w = img.shape[:2]
        max_dimension = 2560
        
        if max(h, w) > max_dimension:
            if h > w:
                new_h = max_dimension
                new_w = int(w * (max_dimension / h))
            else:
                new_w = max_dimension
                new_h = int(h * (max_dimension / w))
            
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
            resized_path = image_path.replace('.png', '_resized.png')
            cv2.imwrite(resized_path, img)
            print(f"[{self.name}] Image resized from {w}x{h} to {new_w}x{new_h}")
            return resized_path
        
        return image_path

    def send_photo_with_caption(self, image_path, caption):
        """Отправляет фото с подписью в Telegram"""
        if not TELEGRAM_BOT_TOKEN:
            print(f"[{self.name}] WARN: no TELEGRAM_BOT_TOKEN — skip")
            return False
        
        try:
            resized_path = self.resize_for_telegram(image_path)
            
            with open(resized_path, "rb") as f:
                r = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                    data={"chat_id": self.config["telegram_chat_id"], "caption": caption},
                    files={"photo": f},
                    timeout=30,
                )
            
            ok = r.ok and r.json().get("ok", False)
            if not ok: 
                print(f"[{self.name}] Telegram error:", r.text)
            else:
                print(f"[{self.name}] Successfully sent photo to Telegram")
                
            return ok
            
        except Exception as e:
            print(f"[{self.name}] Error sending photo: {e}")
            return False

    def send_status_message(self, date_text, has_issues, png_path=None):
        """Отправляет сообщение только при наличии проблем в определенные часы"""
        # Используем время соответствующего города
        city_time = dt.datetime.now(ZoneInfo(self.config["timezone"]))
        current_time = city_time.strftime("%H:%M")
        current_hour = city_time.hour
        
        if has_issues:
            # Отправляем уведомление о проблемах только в рабочие часы
            if current_hour in self.config["notification_hours"]:
                # Проверяем, не отправляли ли уже в этот час про эту дату
                status_file = ART / f"last_alert_{self.city_key}_{date_text}_{current_hour}.txt"
                if not status_file.exists():
                    status_file.touch()
                    # Формируем текст в зависимости от времени проверки
                    if current_hour < 12:
                        day_label = "на сегодня"
                    else:
                        day_label = f"на {date_text}"
                    caption = f"⚠️ {day_label.capitalize()} есть неразобранные заказы. Проверьте CRM ({self.name})"
                    if png_path:
                        result = self.send_photo_with_caption(png_path, caption)
                        if result:
                            print(f"[{self.name}] Sent alert at {current_time} for {date_text}")
                        return result
                else:
                    print(f"[{self.name}] Alert for {date_text} already sent at {current_hour}:00")
            else:
                print(f"[{self.name}] Problem detected at {current_time} {self.config['timezone']} time, but outside notification hours ({self.config['notification_hours']})")
        else:
            print(f"[{self.name}] All orders processed for {date_text} - no notification needed ({self.config['timezone']} time: {current_time})")
        
        return False

    async def monitor(self, max_retries=3):
        """Основная функция мониторинга для одного города"""
        last_error = None
        
        # Повторные попытки при сетевых ошибках
        for attempt in range(1, max_retries + 1):
            try:
                if attempt > 1:
                    # Задержка перед повторной попыткой (10, 20, 30 секунд)
                    wait_time = attempt * 10
                    print(f"[{self.name}] Попытка {attempt}/{max_retries} через {wait_time} секунд...")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"\n🏙️ === Мониторинг {self.name} ===")
                
                png = await self.grab_screenshot()
                present, date_text, png_path = self.check_badge_presence(png)
                sent = self.send_status_message(date_text, present, png_path)
                
                result = {
                    "city": self.name,
                    "present": present, 
                    "sent": sent, 
                    "date": date_text, 
                    "png": png_path
                }
                
                print(f"[{self.name}] RESULT: {result}")
                return result
                
            except Exception as e:
                last_error = e
                error_str = str(e)
                
                # Проверяем, это сетевая ошибка или другая проблема
                is_network_error = any(keyword in error_str.lower() for keyword in [
                    'err_internet_disconnected', 'timeout', 'net::', 'connection', 
                    'network', 'dns', 'unreachable'
                ])
                
                if is_network_error and attempt < max_retries:
                    print(f"[{self.name}] Сетевая ошибка (попытка {attempt}/{max_retries}): {e}")
                else:
                    # Не сетевая ошибка или последняя попытка
                    print(f"[{self.name}] ERROR: {e}")
                    if attempt >= max_retries:
                        print(f"[{self.name}] Все {max_retries} попытки исчерпаны")
                    break
        
        return {"city": self.name, "error": str(last_error)}

async def monitor_all_cities():
    """Мониторинг всех настроенных городов"""
    print("🚀 Запуск мониторинга всех CRM систем...")
    
    tasks = []
    for city_key, config in CRM_CONFIGS.items():
        if config.get("enabled", True):
            monitor = CRMMonitor(city_key, config)
            tasks.append(monitor.monitor())
        else:
            print(f"⏸️ {config['name']} отключен")
    
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        print("\n📊 === ОБЩИЕ РЕЗУЛЬТАТЫ ===")
        for result in results:
            if isinstance(result, Exception):
                print(f"❌ Ошибка: {result}")
            else:
                city = result.get("city", "Unknown")
                if "error" in result:
                    print(f"❌ {city}: {result['error']}")
                else:
                    status = "🚨 ПРОБЛЕМЫ" if result["present"] else "✅ ВСЕ ОК"
                    sent_status = "📤 ОТПРАВЛЕНО" if result["sent"] else "📭 НЕ ОТПРАВЛЕНО"
                    print(f"{status} {city} ({result['date']}): {sent_status}")
    else:
        print("⚠️ Нет активных конфигураций для мониторинга")

if __name__ == "__main__":
    asyncio.run(monitor_all_cities())


