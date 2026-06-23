from playwright.async_api import Page

from config import settings
from models import Job
from utils.browser import random_delay


class AutoFill:
    def __init__(self, page: Page):
        self.page = page

    async def fill_application(self, job: Job) -> None:
        print(f"[auto-fill] Opening {job.source_url}")
        await self.page.goto(job.source_url, wait_until="domcontentloaded")
        await random_delay(2, 4)

        source = job.source
        if source == "indeed":
            await self._fill_indeed()
        elif source == "naukri":
            await self._fill_naukri()
        elif source == "instahyre":
            await self._fill_instahyre()
        elif source == "cutshort":
            await self._fill_cutshort()
        elif source == "wellfound":
            await self._fill_wellfound()
        else:
            print(f"[auto-fill] No fill handler for {source}")

    async def _fill_common(self) -> None:
        for selector in [
            "input[name='name'], input[placeholder*='name']",
            "input[name='email'], input[type='email']",
            "input[name='phone'], input[placeholder*='phone']",
            "textarea[name='cover'], textarea[placeholder*='cover']",
            "input[type='file'], input[accept*='pdf'], input[accept*='resume']",
        ]:
            try:
                el = self.page.locator(selector).first
                if await el.count() == 0:
                    continue
                tag = await el.get_attribute("type") or ""
                name = (await el.get_attribute("name") or "").lower()
                placeholder = (await el.get_attribute("placeholder") or "").lower()

                if "email" in tag or "email" in name or "email" in placeholder:
                    await el.fill(settings.applicant_email)
                elif "phone" in name or "phone" in placeholder:
                    await el.fill(settings.applicant_phone)
                elif "name" in name or "name" in placeholder:
                    await el.fill(settings.applicant_name)
                elif tag == "file" or "resume" in name or "resume" in placeholder:
                    await el.set_input_files(settings.resume_path)
                elif "cover" in name or "cover" in placeholder:
                    await el.fill(settings.applicant_cover_letter)
                await random_delay(0.5, 1.5)
            except Exception:
                continue

    async def _click_apply_button(self) -> None:
        for selector in [
            "button[class*='apply'], a[class*='apply']",
            "button:has-text('Apply')",
            "button:has-text('Easy Apply')",
            "button:has-text('Submit')",
        ]:
            try:
                btn = self.page.locator(selector).first
                if await btn.count() > 0:
                    await btn.click()
                    await random_delay(2, 4)
                    break
            except Exception:
                continue

    async def _fill_indeed(self) -> None:
        await self._click_apply_button()
        await self._fill_common()
        print("[auto-fill] Indeed form pre-filled (review before submitting)")

    async def _fill_naukri(self) -> None:
        await self._click_apply_button()
        await self._fill_common()
        print("[auto-fill] Naukri form pre-filled (review before submitting)")

    async def _fill_instahyre(self) -> None:
        await self._click_apply_button()
        await self._fill_common()
        print("[auto-fill] Instahyre form pre-filled (review before submitting)")

    async def _fill_cutshort(self) -> None:
        await self._click_apply_button()
        await self._fill_common()
        print("[auto-fill] Cutshort form pre-filled (review before submitting)")

    async def _fill_wellfound(self) -> None:
        await self._click_apply_button()
        await self._fill_common()
        print("[auto-fill] Wellfound form pre-filled (review before submitting)")
