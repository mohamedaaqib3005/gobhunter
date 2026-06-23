from abc import ABC, abstractmethod

from playwright.async_api import Page


class BaseScraper(ABC):
    name: str = ""
    login_url: str = ""

    @abstractmethod
    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        ...
