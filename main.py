import asyncio
import os
import shutil
import zipfile
import pdfplumber
from docx import Document
from playwright.async_api import async_playwright
from google import genai
from dotenv import load_dotenv

BASE_DOWNLOAD_DIR = os.path.abspath("downloads")

KEYWORDS = [
    "tramwaj",
    "szyna",
    "zasilacz",
    "czujnik",
    "elementy torowe",
    "części zamienne"
]

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)



def prepare_dir(path):
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def extract_zip_files(tender_dir):
    processed_zips = set()
    while True:
        found_new_zip = False
        for root, _, files in os.walk(tender_dir):
            for file in files:
                if file.lower().endswith(".zip"):
                    zip_path = os.path.join(root, file)
                    if zip_path not in processed_zips:
                        print(f"  📦 Розпаковуємо: {file}...")
                        try:
                            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                                zip_ref.extractall(root)
                            print("  ✅ Розпаковано успішно!")
                        except Exception as e:
                            print(f"  ❌ Помилка розпакування {file}: {e}")
                        
                        processed_zips.add(zip_path)
                        found_new_zip = True
                        
        if not found_new_zip:
            break


def collect_all_text(tender_dir):
    combined_text = ""
    for root, _, files in os.walk(tender_dir):
        for file_name in files:
            file_path = os.path.join(root, file_name)

            if file_name.lower().endswith(".pdf"):
                print(f"  📄 Зчитуємо PDF: {file_name}")
                try:
                    with pdfplumber.open(file_path) as pdf:
                        combined_text += f"\n--- ДОКУМЕНТ: {file_name} ---\n"
                        for page in pdf.pages:
                            combined_text += (page.extract_text() or "") + "\n"
                except Exception as e:
                    print(f"  ❌ Помилка читання PDF {file_name}: {e}")

            elif file_name.lower().endswith(".docx"):
                print(f"  📄 Зчитуємо DOCX: {file_name}")
                try:
                    doc = Document(file_path)
                    combined_text += f"\n--- ДОКУМЕНТ: {file_name} ---\n"
                    combined_text += "\n".join([p.text for p in doc.paragraphs if p.text]) + "\n"
                except Exception as e:
                    print(f"  ❌ Помилка читання DOCX {file_name}: {e}")

            elif file_name.lower().endswith(".txt"):
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        combined_text += f"\n--- ДОКУМЕНТ: {file_name} ---\n" + f.read() + "\n"
                except Exception as e:
                    print(f"  ❌ Помилка читання TXT {file_name}: {e}")

    return combined_text


def analyze_with_ai(tender_title, full_text):
    if not full_text.strip():
        print("  ⚠️ Не вдалося зібрати текст із документів для аналізу.")
        return

    print("  🤖 Надсилаємо документацію на аналіз у Gemini...")
    
    prompt = f"""
    Ти — експерт з аналізу польських публічних закупівель (PZP/SWZ). 
    Проаналізуй надану тендерну документацію для тендера "{tender_title}" і надай детальний, структурований звіт українською мовою.

    Структура звіту:
    1. **Предмет замовлення (Opis przedmiotu zamówienia)**: Що саме закуповується, обсяги, технічні специфікації, артикули/креслення (якщо є).
    2. **Умови участі (Warunki udziału w postępowaniu)**: Кваліфікаційні вимоги (досвід поставок, фінансовий стан, технічні сертифікати).
    3. **Необхідні документи (Wymagane dokumenty/oświadczenia)**: Перелік усіх довідок, декларацій та сертифікатів відповідності.
    4. **Критерії оцінки пропозицій (Kryteria oceny ofert)**: Вага ціни та інших параметрів (гарантія, терміни).
    5. **Строки та терміни (Terminy)**: Дедлайн подачі пропозицій, термін виконання поставок, розмір гарантійного забезпечення (Wadium).
    6. **Особливі примітки/Ризики**: Договірні штрафи, специфічні вимоги до логістики чи упаковки.

    Ось текст тендерної документації:
    {full_text[:10000]}
    """

    # Автоматичний перебір моделей, якщо одна з них недоступна
    candidate_models = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash']
    response = None

    for model_name in candidate_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            break
        except Exception as err:
            if "404" in str(err) or "NOT_FOUND" in str(err):
                continue
            else:
                print(f"  ❌ Помилка при запиті до AI ({model_name}): {err}")
                return

    if response and response.text:
        safe_title = "".join([c if c.isalnum() else "_" for c in tender_title[:30]])
        file_name = f"summary_{safe_title}.txt"
        
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(response.text)
        print(f"  ✅ Звіт успішно збережено у файл '{file_name}'")
    else:
        print("  ❌ Не вдалося отримати відповідь від жодної з моделей Gemini.")


async def process_tenders_for_keyword(page, keyword):
    print(f"\n🔍 Переходимо до списку тендерів за ключовим словом: '{keyword}'...")
    try:
        await page.goto(
            "https://tw.ezamawiajacy.pl/pn/tw/demand/notice/publicpzp/current/list?USER_MENU_HOVER=publicpzpCurrentNoticePublicList",
            wait_until="domcontentloaded"
        )
        await page.wait_for_timeout(2000)

        # Пошук за ключовим словом
        search_input = page.locator("input[type='text']").first
        if await search_input.is_visible():
            await search_input.fill(keyword)
            szukaj_btn = page.locator("button:has-text('SZUKAJ'), input[value='SZUKAJ'], a:has-text('SZUKAJ')").first
            if await szukaj_btn.is_visible():
                await szukaj_btn.click()
            else:
                await page.keyboard.press("Enter")
            await page.wait_for_timeout(3000)

        # Очікуємо появу таблиці з результатами
        try:
            await page.wait_for_selector("table tbody tr", timeout=10000)
        except Exception:
            print(f"  ℹ️ За ключовим словом '{keyword}' тендерів не знайдено.")
            return

        rows = page.locator("table tbody tr")
        count = await rows.count()

        if count == 0:
            print(f"  ℹ️ За ключовим словом '{keyword}' тендерів не знайдено.")
            return

        print(f"  📌 Знайдено тендерів: {count}")
        
        limit = min(count, 5)
        for idx in range(limit):
            try:
                # Повернення до списку після першого тендера
                if idx > 0:
                    await page.goto(
                        "https://tw.ezamawiajacy.pl/pn/tw/demand/notice/publicpzp/current/list?USER_MENU_HOVER=publicpzpCurrentNoticePublicList",
                        wait_until="domcontentloaded"
                    )
                    await page.wait_for_timeout(2000)
                    
                    s_input = page.locator("input[type='text']").first
                    if await s_input.is_visible():
                        await s_input.fill(keyword)
                        szukaj_btn = page.locator("button:has-text('SZUKAJ'), input[value='SZUKAJ'], a:has-text('SZUKAJ')").first
                        if await szukaj_btn.is_visible():
                            await szukaj_btn.click()
                        else:
                            await page.keyboard.press("Enter")
                        await page.wait_for_timeout(3000)

                # Явно чекаємо завантаження таблиці перед вибором рядка
                await page.wait_for_selector("table tbody tr", timeout=10000)
                row = page.locator("table tbody tr").nth(idx)
                
                # Знаходимо текст у першій (номер) або другій (назва) комірці
                target_element = row.locator("td a").first
                if not await target_element.is_visible():
                    target_element = row.locator("td").nth(1)
                if not await target_element.is_visible():
                    target_element = row.locator("td").first

                tender_title = await target_element.inner_text()
                tender_title = tender_title.strip().replace("\n", " ")
                print(f"\n📂 Обробка тендера [{idx+1}/{limit}]: {tender_title}")

                tender_dir = os.path.join(BASE_DOWNLOAD_DIR, f"tender_{keyword}_{idx+1}")
                prepare_dir(tender_dir)

                # Клік через JS
                try:
                    await target_element.evaluate("el => el.click()")
                except Exception:
                    await target_element.click(force=True)

                await page.wait_for_timeout(4000)

                # Перехід у розділ документів
                for tab_name in ["Załączniki", "Dokumenty zamówienia", "Dokumenty", "Dokumentacja"]:
                    tab = page.locator(f"text={tab_name}").first
                    if await tab.is_visible():
                        print(f"  📂 Відкриваємо вкладку: {tab_name}")
                        await tab.click()
                        await page.wait_for_timeout(3000)
                        break

                # Виділення чекбокса 'Вибрати все'
                checkbox = page.locator("table th input[type='checkbox'], table th").first
                if await checkbox.is_visible():
                    print("  ☑️ Натискаємо 'Вибрати все'...")
                    await checkbox.click(force=True)
                    await page.wait_for_timeout(1500)

                # Завантаження документів
                pobierz_btn = page.locator(
                    "button:has-text('POBIERZ'), "
                    "a:has-text('POBIERZ'), "
                    "button:has-text('Pobierz paczkę')"
                ).first

                if await pobierz_btn.is_visible():
                    print("  ⬇️ Завантажуємо пакет документів...")
                    try:
                        async with page.expect_download(timeout=60000) as download_info:
                            await pobierz_btn.evaluate("el => el.click()")
                        download = await download_info.value

                        file_path = os.path.join(tender_dir, download.suggested_filename)
                        await download.save_as(file_path)
                        print(f"  ✅ Успішно завантажено: {download.suggested_filename}")

                        extract_zip_files(tender_dir)
                        full_text = collect_all_text(tender_dir)
                        analyze_with_ai(tender_title, full_text)

                    except Exception as e:
                        print(f"  ❌ Помилка завантаження файлу: {e}")
                else:
                    print("  ⚠️ Кнопку POBIERZ не знайдено на сторінці.")

            except Exception as tender_err:
                print(f"  ❌ Помилка під час обробки тендера [{idx+1}]: {tender_err}")
                continue

    except Exception as kw_err:
        print(f"❌ Помилка під час обробки пошукового слова '{keyword}': {kw_err}")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        for keyword in KEYWORDS:
            await process_tenders_for_keyword(page, keyword)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())