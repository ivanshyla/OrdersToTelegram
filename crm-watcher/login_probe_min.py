import os, asyncio, json
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

load_dotenv()
URL      = os.getenv("CRM_URL")
LOGIN    = os.getenv("CRM_LOGIN")
PASSWORD = os.getenv("CRM_PASSWORD")

OUT = Path("debug"); OUT.mkdir(exist_ok=True)

EMAIL_CSS = (
    "input[name='email'], input[type='email'], "
    "input[placeholder*='mail' i], input[placeholder*='e-mail' i], "
    "input[id*='email' i], input[name*='login' i], input[placeholder*='логин' i]"
)
PASS_CSS = (
    "input[name='password'], input[type='password'], "
    "input[placeholder*='парол' i], input[id*='pass' i]"
)
BTN_CSS = (
    "button:has-text('Войти'), button[type='submit'], "
    "text=/^Войти$/i, text=/login|sign in|вход/i"
)

DASH_PROBES = [
    "text=/Дашборд|Dashboard|Главная/i",
    "text=/Ближайшие дни|Завтра|Сегодня/i",
]

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx = await browser.new_context(viewport={"width":1440,"height":900})
        page = await ctx.new_page()
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=35000)
            await page.screenshot(path=str(OUT/"01_loaded.png"), full_page=True)

            # ищем поля логина
            email = page.locator(EMAIL_CSS).first
            pwd   = page.locator(PASS_CSS).first
            await email.wait_for(timeout=5000)
            await pwd.wait_for(timeout=5000)

            await email.fill(LOGIN, timeout=5000)
            await pwd.fill(PASSWORD, timeout=5000)
            await page.screenshot(path=str(OUT/"02_filled.png"), full_page=True)

            # кликаем сабмит или жмём Enter
            clicked = False
            try:
                await page.locator(BTN_CSS).first.click(timeout=2000); clicked = True
            except Exception:
                pass
            if not clicked:
                try:
                    await pwd.focus(); await page.keyboard.press("Enter")
                except Exception:
                    pass

            await page.wait_for_load_state("networkidle", timeout=35000)
            await page.screenshot(path=str(OUT/"03_after_submit.png"), full_page=True)

            # проверяем, что вошли
            ok = page.url and page.url != URL
            if not ok:
                for probe in DASH_PROBES:
                    try:
                        await page.wait_for_selector(probe, timeout=2000)
                        ok = True; break
                    except PWTimeout:
                        pass

            # сохраняем куки
            await ctx.storage_state(path=str(OUT/"storage_state.json"))

            print("RESULT:", "OK" if ok else "LIKELY_LOGIN_PAGE")
            print("URL_NOW:", page.url)
        finally:
            await ctx.close(); await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
