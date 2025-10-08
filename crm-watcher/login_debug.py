import os, asyncio, json, time
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

load_dotenv()
URL      = os.getenv("CRM_URL")
LOGIN    = os.getenv("CRM_LOGIN")
PASSWORD = os.getenv("CRM_PASSWORD")

OUTDIR = Path("debug"); OUTDIR.mkdir(exist_ok=True)

EMAIL_SEL = [
    'input[name="email"]','input[type="email"]',
    'input[placeholder*="mail" i]','input[placeholder*="e-mail" i]',
    'input[id*="email" i]','input[name*="login" i]','input[placeholder*="логин" i]',
]
PASS_SEL = [
    'input[name="password"]','input[type="password"]',
    'input[placeholder*="парол" i]','input[id*="pass" i]',
]
BTN_SEL = [
    'button:has-text("Войти")','button[type="submit"]',
    'text=/^Войти$/i','text=/sign in|login|вход/i',
]

DASH_PROBES = [
    'text=/Дашборд|Dashboard|Главная/i',
    'text=/Ближайшие дни|Завтра|Сегодня/i',
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

async def sshot(page, name):
    await page.screenshot(path=str(OUTDIR/f"{name}.png"), full_page=True)

def log_write(txt):
    with open(OUTDIR/"debug.log","a",encoding="utf-8") as f:
        f.write(txt.rstrip()+"\n")

async def list_inputs_in_frame(frame, tag="input"):
    return await frame.evaluate("""(tag)=>{
      const els=[...document.querySelectorAll(tag)];
      return els.map(e=>({
        tag:e.tagName.toLowerCase(),
        type:e.getAttribute('type'),
        name:e.getAttribute('name'),
        id:e.id,
        placeholder:e.getAttribute('placeholder'),
        autocomplete:e.getAttribute('autocomplete')
      }));
    }""", tag)

async def find_in_all_frames(context, selectors):
    for page in context.pages:
        # check main frame
        for sel in selectors:
            try:
                await page.locator(sel).first.wait_for(timeout=1500)
                return page.main_frame, sel
            except: pass
        # check child frames
        for fr in page.frames:
            for sel in selectors:
                try:
                    await fr.wait_for_selector(sel, timeout=1500)
                    return fr, sel
                except: pass
    return None, None

async def debug_login():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox","--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        ctx = await browser.new_context(
            viewport={"width":1440,"height":900},
            user_agent=UA,
            locale="ru-RU",
            timezone_id="Europe/Warsaw",
        )

        # логи консоли/сетевые
        def on_console(msg): log_write(f"[console] {msg.type()}: {msg.text()}")
        def on_request(req): log_write(f"[request] {req.method()} {req.url}")
        async def on_response(res):
            try:
                log_write(f"[response] {res.status} {res.url}")
            except: pass

        page = await ctx.new_page()
        page.on("console", on_console)
        page.on("request", on_request)
        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=35000)
            await sshot(page, "01_loaded")

            # быстрая проверка Cloudflare/капч
            body_text = (await page.content()).lower()
            if "just a moment" in body_text or "cloudflare" in body_text:
                log_write("[hint] Похоже на защиту Cloudflare/бот-чек.")
            if "captcha" in body_text or "recaptcha" in body_text or "hcaptcha" in body_text:
                log_write("[hint] Обнаружены признаки CAPTCHA на странице.")

            # Найти поля логина (во всех фреймах)
            fr_email, sel_email = await find_in_all_frames(ctx, EMAIL_SEL)
            fr_pass,  sel_pass  = await find_in_all_frames(ctx, PASS_SEL)

            # Если не нашли — распечатать все inputs для диагностики
            if not sel_email or not sel_pass:
                for fr in page.frames:
                    inputs = await list_inputs_in_frame(fr)
                    log_write(f"[inputs in frame {fr.name or 'main'}]: {inputs}")

            if not sel_email or not sel_pass:
                await sshot(page, "02_login_no_selectors")
                print("RESULT: FAIL_NO_SELECTORS")
                return

            # Ввод
            await fr_email.fill(sel_email, LOGIN)
            await fr_pass.fill(sel_pass, PASSWORD)
            await sshot(page, "03_filled")

            # Нажатие кнопки/Enter
            clicked = False
            for fr, sels in [(fr_pass, BTN_SEL), (fr_email, BTN_SEL)]:
                for s in sels:
                    try:
                        await fr.click(s, timeout=2000); clicked = True; break
                    except: continue
                if clicked: break
            if not clicked:
                try:
                    await fr_pass.focus(sel_pass)
                    await fr_pass.press(sel_pass, "Enter")
                    clicked = True
                except: pass

            await page.wait_for_load_state("networkidle", timeout=35000)
            await sshot(page, "04_after_submit")

            # Проверка: сменился ли URL / появились ли признаки дашборда
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

            # Сохраняем куки состояния
            state = await ctx.storage_state()
            (OUTDIR/"storage_state.json").write_text(json.dumps(state), encoding="utf-8")

            print("RESULT:", "OK" if ok else "LIKELY_BLOCKED_OR_WRONG_CREDS")
            print("URL_NOW:", page.url)
            if not ok:
                print("HINT:",
                      "Проверь: (1) нет ли 2FA/капчи/Cloudflare; (2) верны ли селекторы; (3) не меняет ли страница URL после логина.")
        finally:
            await ctx.close(); await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_login())
