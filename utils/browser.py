import asyncio
import random
from collections.abc import Callable

from playwright.async_api import Page, async_playwright


USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
]


VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
]


async def _stealth_page(page: Page) -> None:
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        window.chrome = { runtime: {} };
    """)


def _normalize_cookies(cookies: list[dict]) -> list[dict]:
    SAME_SITE_MAP = {
        "no_restriction": "None",
        "lax": "Lax",
        "strict": "Strict",
    }
    PLAYWRIGHT_KEYS = {"name", "value", "url", "domain", "path",
                       "expires", "httpOnly", "secure", "sameSite"}
    cleaned = []
    for c in cookies:
        normalized = {k: v for k, v in c.items() if k in PLAYWRIGHT_KEYS and v is not None}
        ss = c.get("sameSite")
        if ss is not None:
            normalized["sameSite"] = SAME_SITE_MAP.get(ss, ss)
        if "expirationDate" in c and "expires" not in normalized:
            normalized["expires"] = int(c["expirationDate"])
        cleaned.append(normalized)
    return cleaned


async def scrape_with_cookies(
    url: str,
    handler: Callable,
    cookies: list[dict] | None = None,
    headless: bool = True,
) -> list | None:
    ua = random.choice(USER_AGENTS)
    vp = random.choice(VIEWPORTS)

    async with async_playwright() as p:
        browser = await p.firefox.launch(
            headless=headless,
            args=["--no-sandbox"],
        )
        context = await browser.new_context(
            user_agent=ua,
            viewport=vp,
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            ignore_https_errors=True,
        )
        if cookies:
            await context.add_cookies(_normalize_cookies(cookies))

        page = await context.new_page()
        await _stealth_page(page)

        try:
            result = await handler(page)
            return result
        except Exception as e:
            print(f"  Error: {e}")
            return None
        finally:
            await context.close()
            await browser.close()


async def random_delay(min_s: float = 1.0, max_s: float = 4.0) -> None:
    await asyncio.sleep(random.uniform(min_s, max_s))


async def human_like_scroll(page) -> None:
    for _ in range(random.randint(2, 5)):
        await page.evaluate(f"window.scrollBy(0, {random.randint(300, 700)})")
        await random_delay(0.5, 2.0)
