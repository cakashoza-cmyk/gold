"""Browser check: renders main screen in gu/hi/en and every details tab, takes mobile screenshots, reports JS errors.
Usage: python3 test/verify.py <base-url> [out-dir]"""
import sys, json, asyncio
from playwright.async_api import async_playwright
BASE = sys.argv[1]; OUT = sys.argv[2] if len(sys.argv) > 2 else "shots"
TABS = ["today", "landed", "rules", "trend", "track", "sources"]
IDS = ["a-main", "a-reason", "p-big", "p-sub", "p-sub2", "p-ind", "i-main", "i-sub", "h-main", "h-sub", "f-main"]


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        errs = []
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True, timezone_id="Asia/Kolkata")
        pg = await ctx.new_page(); pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e))); pg.on("console", lambda m: m.type == "error" and errs.append("console: " + m.text))
        await pg.goto(BASE, wait_until="networkidle"); await pg.evaluate("localStorage.clear()"); await pg.reload(wait_until="networkidle"); await pg.wait_for_timeout(1200)
        q = "(" + json.dumps(IDS) + ").reduce((o,k)=>(o[k]=document.getElementById(k).textContent,o),{})"
        for lang in ("gu", "hi", "en"):
            await pg.click(f"#langs button[data-l={lang}]"); await pg.wait_for_timeout(300)
            print(f"MAIN {lang}:", json.dumps(await pg.evaluate(q), ensure_ascii=False))
            await pg.screenshot(path=f"{OUT}/main_{lang}_mobile.png", full_page=True)
        await pg.click("#langs button[data-l=gu]")
        await pg.fill("#q-input", "135000"); await pg.dispatch_event("#q-input", "change"); await pg.wait_for_timeout(300)
        print("dealer compare:", await pg.text_content("#q-res"))
        wa = await pg.evaluate("(()=>{let u=null;window.open=(x)=>{u=x};document.getElementById('wa-btn').click();return decodeURIComponent(u)})()")
        print("WA:", wa)
        await pg.click("#q-clear")
        # details on mobile
        await pg.goto(BASE + "#details", wait_until="networkidle"); await pg.wait_for_timeout(1000)
        for t in TABS:
            await pg.click(f".tab[data-s={t}]"); await pg.wait_for_timeout(250)
            txt = await pg.evaluate(f"document.getElementById('s-{t}').innerText")
            print(f"tab {t}: {len(txt)} chars; warn={'Could not render' in txt}")
            await pg.screenshot(path=f"{OUT}/details_{t}_mobile.png", full_page=True)
        # rule edit recomputes the call
        await pg.click(".tab[data-s=rules]")
        await pg.fill("input[data-k=dipPct]", "10"); await pg.dispatch_event("input[data-k=dipPct]", "change"); await pg.wait_for_timeout(300)
        await pg.click(".tab[data-s=today]"); print("call with dip 10%:", (await pg.inner_text("#s-today .call")))
        await pg.evaluate("localStorage.clear()")
        await b.close()
        print("ERRORS:", errs or "none")
        if errs:
            sys.exit(1)

asyncio.run(main())
