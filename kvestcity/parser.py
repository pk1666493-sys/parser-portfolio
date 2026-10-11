
import asyncio
import csv
import re
from playwright.async_api import async_playwright

BASE = "https://kvest-moscow.ru"
CATEGORY_URL = f"{BASE}/categories/xorror"
OUTPUT_CSV = "quests.csv"
OUTPUT_XLSX = "quests.xlsx"
MAX_PAGES = 20


def clean_price(raw):
    digits = re.sub(r"[^\d]", "", raw or "")
    return int(digits) if digits else 0


async def get_all_quest_links(page):
    all_links = set()
    for page_num in range(1, MAX_PAGES + 1):
        url = CATEGORY_URL if page_num == 1 else f"{CATEGORY_URL}?page={page_num}"
        print(f"[листинг {page_num}] {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1500)
        except Exception as e:
            print(f"  не загрузилось: {e}")
            break

        links = await page.eval_on_selector_all(
            "a[href*='/kvesty/']",
            "els => [...new Set(els.map(e => e.href.split('?')[0].split('#')[0]))]"
        )
        links = [l for l in links if re.search(r"/kvesty/[^/]+/?$", l)]

        new = set(links) - all_links
        if not new:
            print("  новых нет, стоп")
            break

        all_links.update(new)
        print(f"  +{len(new)} новых, всего: {len(all_links)}")
        await page.wait_for_timeout(700)

    return sorted(all_links)


async def try_selectors(page, selectors):
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                val = await el.inner_text()
                if val and val.strip():
                    return val.strip()
        except Exception:
            continue
    return ""


async def get_details(page):
    try:
        await page.wait_for_selector(".kc-detail-bar__cell", timeout=15000)
    except Exception:
        pass

    try:
        data = await page.evaluate("""
            () => {
                const result = {players: '', duration: '', age: '', difficulty: ''};
                const cells = document.querySelectorAll('.kc-detail-bar__cell');
                for (const cell of cells) {
                    const dt = (cell.querySelector('dt')?.innerText || '').trim().toLowerCase();
                    const dd = (cell.querySelector('dd')?.innerText || '').trim();
                    if (!dd) continue;
                    if (dt.includes('игрок') || dt.includes('человек')) result.players = dd;
                    else if (dt.includes('длительн') || dt.includes('минут')) result.duration = dd;
                    else if (dt.includes('возраст')) result.age = dd;
                    else if (dt.includes('сложност')) result.difficulty = dd;
                }
                return result;
            }
        """)
        return data
    except Exception:
        return {"players": "", "duration": "", "age": "", "difficulty": ""}


async def get_description(page):
    try:
        await page.wait_for_selector("#opisanie .prose-content", timeout=15000)
    except Exception:
        pass

    try:
        text = await page.evaluate("""
            () => {
                const section = document.querySelector('#opisanie .prose-content')
                             || document.querySelector('#opisanie');
                if (!section) return '';

                const parts = [];
                const walker = document.createTreeWalker(
                    section, NodeFilter.SHOW_ELEMENT, null
                );
                let node = walker.currentNode;
                while (node) {
                    const tag = node.tagName;
                    if (tag === 'H2' || tag === 'H3') break;
                    if (tag === 'P' || tag === 'LI') {
                        const t = (node.innerText || '').trim();
                        if (t.length >= 20) parts.push(t);
                    }
                    node = walker.nextNode();
                }

                return parts.join('\\n\\n');
            }
        """)
        if text and len(text) > 100:
            return text
    except Exception as e:
        print(f"    get_description упал: {e}")

    meta = await page.query_selector("meta[name='description']")
    if meta:
        return (await meta.get_attribute("content")) or ""
    return ""


async def parse_quest(page, url):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
    except Exception as e:
        print(f"  ошибка {url} — {e}")
        return None

    name = await try_selectors(page, ["h1", "h1.title"])
    price_raw = await try_selectors(page, [
        "[class*='price']", "[class*='cost']", ".price-value",
    ])
    address = await try_selectors(page, [
        "[class*='address']", "[class*='addr']", "[itemprop='address']",
    ])

    description = await get_description(page)
    details = await get_details(page)
    price_num = clean_price(price_raw)

    data = {
        "name": name,
        "price": price_raw,
        "price_num": price_num,
        "address": address,
        "players": details.get("players", ""),
        "duration": details.get("duration", ""),
        "age": details.get("age", ""),
        "difficulty": details.get("difficulty", ""),
        "description": description,
        "url": url,
    }

    print(f"  {price_num:>7} ₽ | {details.get('difficulty','?'):<8} | "
          f"{details.get('players','?'):<12} | {details.get('duration','?'):<10} | "
          f"описание: {len(description):>5} | {name[:40] if name else url}")
    return data


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        print("=== Этап 1: сбор ссылок ===")
        links = await get_all_quest_links(page)
        print(f"\nВсего ссылок: {len(links)}\n")

        print("=== Этап 2: парсинг карточек ===")
        results = []
        for i, link in enumerate(links, 1):
            print(f"[{i}/{len(links)}] {link}")
            data = await parse_quest(page, link)
            if data and data["name"]:
                results.append(data)
            await page.wait_for_timeout(700)

        await browser.close()

    if not results:
        print("❌ Ничего не спарсилось")
        return

    results.sort(key=lambda x: (x["price_num"] == 0, x["price_num"]))

    fields = ["name", "price", "price_num", "address", "players",
              "duration", "age", "difficulty", "description", "url"]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)
    print(f"\n✅ CSV: {OUTPUT_CSV} ({len(results)} записей)")

    try:
        import pandas as pd
        df = pd.DataFrame(results, columns=fields)
        df.to_excel(OUTPUT_XLSX, index=False, engine="openpyxl")
        print(f"✅ XLSX: {OUTPUT_XLSX} ({len(results)} записей)")
    except ImportError:
        print("⚠️ pandas/openpyxl не установлены — только CSV")


if __name__ == "__main__":
    asyncio.run(main())
