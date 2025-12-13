import time
import re
import os
import json
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials

# 셀레니움 관련
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 1. 설정
SHEET_URL = "https://docs.google.com/spreadsheets/d/1nKPVCZ6zAOfpqCjV6WfjkzCI55FA9r2yvi9XL3iIneo/edit"
TARGET_GID = 639559541  # 워크시트 ID 확인 필수
SCRAPE_URL = "https://offercent.co.kr/company-list?jobCategories=0040002%2C0170004"

def get_google_sheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(os.environ['GOOGLE_CREDENTIALS'])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    spreadsheet = client.open_by_url(SHEET_URL)
    worksheet = None
    
    for sheet in spreadsheet.worksheets():
        if str(sheet.id) == str(TARGET_GID):
            worksheet = sheet
            break
            
    if worksheet is None:
        raise Exception(f"GID가 {TARGET_GID}인 시트를 찾을 수 없습니다.")
    
    print(f"📂 연결된 시트: {worksheet.title}")
    return worksheet

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # 봇 탐지 방지
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    chrome_options.add_argument(f"user-agent={user_agent}")
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

def get_projects():
    driver = get_driver()
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        print("🌐 오퍼센트 접속 중...")
        driver.get(SCRAPE_URL)
        
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(5) 

        # 스크롤 다운 (데이터 확보)
        for i in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        
        elements = driver.find_elements(By.TAG_NAME, "a")
        print(f"🔍 발견된 전체 링크 수: {len(elements)}개")

        # [핵심] 제목으로 절대 들어오면 안 되는 단어들 (필터링)
        BAD_KEYWORDS = ["채용 중인 공고", "채용마감", "마감임박", "상시채용", "NEW", "D-"]

        for idx, elem in enumerate(elements):
            try:
                full_url = elem.get_attribute("href")
                if not full_url or full_url == SCRAPE_URL: continue
                
                raw_text = elem.text.strip()
                if not raw_text: continue

                # 줄바꿈 기준으로 텍스트 분리
                lines = raw_text.split('\n')
                
                # 불필요한 단어가 포함된 줄은 아예 삭제
                cleaned_lines = []
                for line in lines:
                    text = line.strip()
                    if not text: continue
                    
                    is_bad = False
                    for bad in BAD_KEYWORDS:
                        if bad in text:
                            is_bad = True
                            break
                    if not is_bad:
                        cleaned_lines.append(text)

                # 필터링 후 남은 게 별로 없으면 스킵
                if len(cleaned_lines) < 2:
                    continue

                # 순서: 0번=회사명, 1번=제목 (오퍼센트 일반적 구조)
                company = cleaned_lines[0]
                title = cleaned_lines[1]

                # 예외 처리: 제목이 너무 짧으면 그 다음 줄 확인
                if len(title) <= 3 and len(cleaned_lines) > 2:
                    title = cleaned_lines[2]

                # 저장 조건
                if len(title) > 1 and len(company) > 1:
                    # 중복 방지 (URL 기준)
                    if not any(d['url'] == full_url for d in new_data):
                        new_data.append({
                            'title': title,
                            'company': company,
                            'url': full_url,
                            'scraped_at': today
                        })
            except Exception:
                continue
                
    except Exception as e:
        print(f"❌ 크롤링 에러: {e}")
    finally:
        driver.quit()
            
    print(f"🎯 최종 수집된 공고: {len(new_data)}개")
    
    # 로그에 샘플 출력 (성공 여부 확인용)
    if len(new_data) > 0:
        print("📊 [샘플 데이터]")
        for i in range(min(3, len(new_data))):
             print(f"   제목: {new_data[i]['title']} / 회사: {new_data[i]['company']}")

    return new_data

def update_sheet(worksheet, data):
    all_values = worksheet.get_all_values()
    
    if not all_values:
        headers = ['title', 'company', 'url', 'scraped_at', 'status']
        worksheet.append_row(headers)
        all_values = [headers]
    
    headers = all_values[0]
    try:
        idx_title = headers.index('title')
        idx_company = headers.index('company')
        idx_url = headers.index('url')
        idx_scraped_at = headers.index('scraped_at')
        idx_status = headers.index('status')
    except:
        print("⛔ 헤더 오류: 컬럼명을 찾을 수 없습니다.")
        return

    existing_urls = set()
    if len(all_values) > 1:
        for row in all_values[1:]:
            if len(row) > idx_url:
                existing_urls.add(row[idx_url])

    rows_to_append = []
    empty_row = [''] * len(headers)

    for item in data:
        if item['url'] in existing_urls:
            continue
        new_row = empty_row.copy()
        new_row[idx_title] = item['title']
        new_row[idx_company] = item['company']
        new_row[idx_url] = item['url']
        new_row[idx_scraped_at] = item['scraped_at']
        new_row[idx_status] = 'archived'
        rows_to_append.append(new_row)

    if rows_to_append:
        worksheet.append_rows(rows_to_append)
        print(f"💾 {len(rows_to_append)}개 저장 완료!")
    else:
        print("ℹ️ 저장할 새로운 공고가 없습니다.")

if __name__ == "__main__":
    try:
        sheet = get_google_sheet()
        projects = get_projects()
        update_sheet(sheet, projects)
    except Exception as e:
        print(f"🚨 실패: {e}")
