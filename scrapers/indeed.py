import asyncio
from html import unescape
import json
import re
import urllib.parse

from playwright.async_api import Page

from scrapers.base import BaseScraper
from utils.browser import human_like_scroll, random_delay


def _clean_html_description(html_content: str) -> str:
    """Convert Indeed HTML job description to clean formatted text."""
    if not html_content:
        return ""
    text = re.sub(r"<li[^>]*>", "• ", html_content, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<(p|div|h[1-6]|ul|ol|tr)[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|h[1-6]|ul|ol|tr)>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _extract_job_key(url: str) -> str | None:
    """Extract Indeed job key (jk parameter or direct ID) from URL."""
    if not url:
        return None
    url = str(url).strip()
    url = re.sub(r"\\([?&=/])", r"\1", url)
    m = re.search(r"(?:[?&]|\b)jk=([a-zA-Z0-9]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"/viewjob/([a-zA-Z0-9]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"(?:[?&]|\b)jobkey=([a-zA-Z0-9]+)", url)
    if m:
        return m.group(1)
    return None



class IndeedScraper(BaseScraper):
    name = "indeed"
    login_url = "https://in.indeed.com"

    async def search(self, page: Page, query: str, locations: list[str]) -> list[dict]:
        """Search jobs on Indeed by extracting Mosaic JSON and DOM fallback."""
        page.set_default_timeout(30000)
        all_jobs = []
        seen_urls = set()

        for loc in locations:
            url = f"https://in.indeed.com/jobs?q={urllib.parse.quote_plus(query)}&l={urllib.parse.quote_plus(loc)}"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            except Exception:
                continue

            await random_delay(1, 2)
            await human_like_scroll(page)
            await random_delay(1, 2)

            parsed_jobs = await self._parse_listing(page)
            for j in parsed_jobs:
                u = j.get("source_url")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    all_jobs.append(j)

        return all_jobs

    async def _parse_listing(self, page: Page) -> list[dict]:
        """Extract job listings from Mosaic providerData or DOM."""
        results = await page.evaluate("""
            () => {
                const list = [];

                // 1. Extract from window.mosaic.providerData
                try {
                    const mosaic = window.mosaic;
                    if (mosaic && mosaic.providerData && mosaic.providerData['mosaic-provider-jobcards']) {
                        const jobcards = mosaic.providerData['mosaic-provider-jobcards'];
                        const rawResults = jobcards.metaData?.mosaicProviderJobCardsModel?.results || [];
                        for (const c of rawResults) {
                            const jk = c.jobkey || c.jobKey;
                            let jobUrl = '';
                            if (jk) {
                                jobUrl = 'https://in.indeed.com/viewjob?jk=' + jk;
                            } else if (c.viewJobLink) {
                                jobUrl = c.viewJobLink.startsWith('http') ? c.viewJobLink : 'https://in.indeed.com' + c.viewJobLink;
                            }

                            const salary = c.salarySnippet?.text || c.estimatedSalary?.formatted || null;
                            const skills = (c.taxonomyAttributes || []).map(t => t.label || t.name).filter(Boolean);

                            if (c.title && jobUrl) {
                                list.push({
                                    title: c.title.trim(),
                                    company: (c.company || c.truncatedCompany || 'Unknown').trim(),
                                    location: (c.formattedLocation || 'Bangalore/Remote').trim(),
                                    url: jobUrl,
                                    salary: salary,
                                    skills: skills
                                });
                            }
                        }
                    }
                } catch(e) {}

                if (list.length > 0) {
                    return list;
                }

                // 2. DOM fallback
                const cards = document.querySelectorAll('div.job_seen_beacon, td.resultContent, div.cardOutline');
                for (const card of cards) {
                    try {
                        const titleEl = card.querySelector('h2.jobTitle a, a.jcs-JobTitle, a[data-jk]');
                        if (!titleEl) continue;

                        const title = titleEl.innerText.trim();
                        let url = titleEl.getAttribute('href') || '';
                        if (url && !url.startsWith('http')) {
                            url = 'https://in.indeed.com' + url;
                        }

                        const compEl = card.querySelector('[data-testid="company-name"], span.companyName');
                        const company = compEl ? compEl.innerText.trim() : 'Unknown';

                        const locEl = card.querySelector('[data-testid="text-location"], div.companyLocation');
                        const location = locEl ? locEl.innerText.trim() : 'Bangalore/Remote';

                        const salEl = card.querySelector('[data-testid="job-salary"], .salary-snippet-container');
                        const salary = salEl ? salEl.innerText.trim() : null;

                        if (title && url) {
                            list.push({
                                title: title,
                                company: company,
                                location: location,
                                url: url,
                                salary: salary,
                                skills: []
                            });
                        }
                    } catch(e) {}
                }

                return list;
            }
        """)

        return [
            {
                "title": item["title"],
                "company": item["company"],
                "location": item["location"],
                "source": self.name,
                "source_url": item["url"],
                "salary_range": item.get("salary"),
                "key_skills": item.get("skills", []),
            }
            for item in results
            if item.get("title") and item.get("url")
        ]

    async def fetch_description(self, page: Page, url: str) -> str | None:
        """Fetch the full text description for a given Indeed job URL."""
        details = await self.get_job_details(page, url)
        return details.get("description")

    async def get_job_details(self, page: Page, url: str) -> dict:
        """Extract full details and structured description from an Indeed job page."""
        if not url:
            return {}

        jk = _extract_job_key(url)
        target_url = f"https://in.indeed.com/viewjob?jk={jk}" if jk else url
        if not target_url.startswith("http"):
            target_url = f"https://in.indeed.com{target_url if target_url.startswith('/') else '/' + target_url}"

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(2000)

            data = await page.evaluate("""
                () => {
                    const info = {};

                    // 1. Check window._initialData viewJobClientSideModel
                    try {
                        const model = window._initialData?.viewJobClientSideModel || {};
                        const jobInfo = model.jobInfoWrapperModel?.jobInfoModel;

                        if (model.jobTitle || jobInfo?.jobInfoHeaderModel?.jobTitle) {
                            info.title = model.jobTitle || jobInfo?.jobInfoHeaderModel?.jobTitle;
                        }

                        const company = model.companyTabModel?.companyName ||
                                        jobInfo?.jobInfoHeaderModel?.companyName ||
                                        model.employerInsightsModel?.companyName ||
                                        model.jobInfoHeaderModel?.companyName;
                        if (company) {
                            info.company = company;
                        }

                        if (model.jobLocation || jobInfo?.jobInfoHeaderModel?.formattedLocation) {
                            info.location = model.jobLocation || jobInfo?.jobInfoHeaderModel?.formattedLocation;
                        }

                        const rawDesc = jobInfo?.sanitizedJobDescription?.content ||
                                        jobInfo?.sanitizedJobDescription ||
                                        jobInfo?.jobDescriptionSectionModel?.content;
                        if (rawDesc && typeof rawDesc === 'string') {
                            info.description = rawDesc;
                            info.source = 'initialData';
                        }
                    } catch(e) {}

                    // 2. Check JSON-LD
                    if (!info.description) {
                        try {
                            const ldScripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
                            for (const s of ldScripts) {
                                const d = JSON.parse(s.innerText);
                                if (d['@type'] === 'JobPosting') {
                                    info.title = info.title || d.title;
                                    info.company = info.company || d.hiringOrganization?.name;
                                    if (d.jobLocation?.address) {
                                        const addr = d.jobLocation.address;
                                        info.location = info.location || [addr.addressLocality, addr.addressRegion, addr.addressCountry].filter(Boolean).join(', ');
                                    }
                                    if (d.description) {
                                        info.description = d.description;
                                        info.source = 'jsonld';
                                        break;
                                    }
                                }
                            }
                        } catch(e) {}
                    }

                    // 3. Fallback to DOM elements with stitching
                    if (!info.description) {
                        const descContainer = document.querySelector('#jobDescriptionText, [data-testid="jobDescriptionText"], .jobsearch-jobDescriptionText');
                        if (descContainer) {
                            const directChildren = Array.from(descContainer.children);
                            if (directChildren.length > 0) {
                                const lines = [];
                                for (const child of directChildren) {
                                    if (child.tagName === 'UL' || child.tagName === 'OL') {
                                        const lis = child.querySelectorAll('li');
                                        for (const li of lis) {
                                            const liText = li.innerText.trim();
                                            if (liText) lines.push('• ' + liText);
                                        }
                                    } else {
                                        const t = child.innerText.trim();
                                        if (t) lines.push(t);
                                    }
                                }
                                info.description = lines.join('\\n\\n');
                            }
                            if (!info.description || info.description.trim().length < 20) {
                                info.description = descContainer.innerText.trim();
                            }
                            info.source = 'dom';
                        }
                    }

                    // Fallback title / company / location from DOM if missing
                    if (!info.title) {
                        const tEl = document.querySelector('h1[data-testid="jobsearch-JobInfoHeader-title"], h1.jobTitle, h1');
                        info.title = tEl ? tEl.innerText.trim() : null;
                    }
                    if (!info.company) {
                        const cEl = document.querySelector('[data-testid="inlineHeader-companyName"], div.jobsearch-CompanyInfoContainer, span.companyName');
                        info.company = cEl ? cEl.innerText.trim() : 'Unknown';
                    }
                    if (!info.location) {
                        const lEl = document.querySelector('[data-testid="inlineHeader-companyLocation"], div.companyLocation');
                        info.location = lEl ? lEl.innerText.trim() : 'Bangalore/Remote';
                    }
                    if (!info.salary) {
                        const sEl = document.querySelector('#salaryInfoAndJobType, [data-testid="jobsearch-OtherJobDetailsContainer"]');
                        info.salary = sEl ? sEl.innerText.trim() : null;
                    }

                    return info;
                }
            """)

            raw_desc = data.get("description") or ""
            description = _clean_html_description(raw_desc) if raw_desc else None

            return {
                "title": data.get("title"),
                "company": data.get("company") or "Unknown",
                "location": data.get("location") or "Bangalore/Remote",
                "salary_range": data.get("salary"),
                "key_skills": [],
                "description": description,
                "source_url": target_url,
                "source": self.name,
            }
        except Exception as e:
            return {"description": None, "source_url": target_url, "source": self.name, "error": str(e)}
