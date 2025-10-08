import os, asyncio, json
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

load_dotenv()
URL      = os.getenv("CRM_URL")
LOGIN    = os.getenv("CRM_LOGIN")
PASSWORD = os.getenv("CRM_PASSWORD")

EMAIL_CANDIDATES = [
    'input[name="email"]', 'input[type="email"]',
    'input[placeholder*="mail" i]', 'input[placeholder*="e-mail" i]',
    'input[placeholder*="Введите ваш e-mail" i]', 'input[id*="email" i]',
]
PWD_CANDIDATES = [
    'input[name="password"]', 'input[type="password"]',
    'input[placeholder*="парол" i]', 'input[placeholder*="Введите пароль" i]',
    'input[id*="pass" i]',
]
BTN_CANDIDATES = [
    'button:has-text("Войти")', 'button[type="submit"]',
    'text=/^Войти$/i', 'text=/login|sign in|вход/i',
]
DASH_PROBES = [
    'text=/Дашборд|Dashboard|Главная/i',
    'text=/Ближайшие дни|Завтра|Сегодня/i',
]

async def try_fill(page, selectors, value):
    for sel in selectors:
        try:
            await page.fill(sel, value, timeout=3000); return sel
        except Exception: continue
    return None

async def try_click(page, selectors):
    for sel in selectors:
        try:
            await page.click(sel, timeout=3000); return sel
        except Exception: continue
    return None

async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage"]
        )
        ctx = await browser.new_context(viewport={"width":1440,"height":900})
        page = await ctx.new_page()
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=30000)

            email_sel = await try_fill(page, EMAIL_CANDIDATES, LOGIN)
            pwd_sel   = await try_fill(page, PWD_CANDIDATES, PASSWORD)
            btn_sel   = await try_click(page, BTN_CANDIDATES)
            if not btn_sel and pwd_sel:
                try:
                    await page.focus(pwd_sel)
                    await page.keyboard.press("Enter")
                except Exception:
                    pass

            await page.wait_for_load_state("networkidle", timeout=30000)

            ok = False
            if page.url and page.url != URL:
                ok = True
            else:
                for probe in DASH_PROBES:
                    try:
                        await page.wait_for_selector(probe, timeout=2000)
                        ok = True; break
                    except PWTimeout:
                        pass

            await page.screenshot(path="probe.png", full_page=True)
            state = await ctx.storage_state()
            with open("storage_state.json","w") as f:
                f.write(json.dumps(state))

            print("RESULT:", "OK" if ok else "LIKELY_LOGIN_PAGE")
            print("DEBUG:", {"email_sel":email_sel, "pwd_sel":pwd_sel, "btn_sel":btn_sel, "url":page.url})
            if not ok:
                print("HINT: если есть 2FA/капча/Cloudflare — нужен тех-аккаунт без 2FA и белый IP.")
        finally:
            await ctx.close(); await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
