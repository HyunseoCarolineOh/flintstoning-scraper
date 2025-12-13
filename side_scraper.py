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

# 설정
SHEET_URL = "https://docs.google.com/spreadsheets/d/1nKPVCZ6zAOfpqCjV6WfjkzCI55FA9r2yvi9XL3iIneo/edit"
TARGET_GID = 1818966683
SCRAPE_URL = "https://sideproject.co.kr/projects"

# 지역 키워드
REGION_KEYWORDS = [
    "서울", "경기", "인천", "대전", "대구", "부산", "광주", "울산", "세종", 
    "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주", "온라인"
]

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
    
    # [중요] 봇 탐지 우회 옵션 추가
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # 자동화 제어 문구 제거 (봇 탐지 방지)
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    
    # 일반 사용자처럼 보이게 User-Agent 설정
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    chrome_options.add_argument(f"user-agent={user_agent}")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    # navigator.webdriver 속성을 undefined로 변경 (자바스크립트 탐지 우회)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """
    })
    
    return driver

def get_projects():
    driver = get_driver()
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        print("🌐 사이트 접속 중...")
        driver.get(SCRAPE_URL)
        
        # [수정] 로딩 대기 시간 및 방식 변경
        try:
            print("⏳ 데이터 로딩 대기 중 (최대 30초)...")
            # 20초 -> 30초로 연장
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a"))
            )
            # 확실한 렌더링을 위해 강제 대기 추가
            time.sleep(5) 
            print("✅ 로딩 완료")
        except:
            print("⚠️ 대기 시간 초과 (스크린샷 저장)")
            driver.save_screenshot("error_screenshot.png") # 에러 시 상태 확인용
            
        # 모든 링크 수집
        elements = driver.find_elements(By.TAG_NAME, "a")
        print(f"🔍 발견된 링크: {len(elements)}개")

        for elem in elements:
            try:
                raw_link = elem.get_attribute("href")
                if not raw_link: continue

                # 사이드프로젝트 사이트 구조에 맞는 링크 필터링
                if "idx=" in raw_link and "bmode=view" in raw_link:
                    raw_text = elem.text.strip()
                    if not raw_text: continue 

                    lines = raw_text.split('\n')
                    title = lines[0] if lines else raw_text
                    
                    location = "미정"
                    for keyword in REGION_KEYWORDS:
                        if keyword in raw_text:
                            location = keyword
                            break
                    
                    idx_match = re.search(r'idx=(\d+)', raw_link)
                    if idx_match:
                        idx = idx_match.group(1)
                        full_url = f"https://sideproject.co.kr/projects/?bmode=view&idx={idx}"
                        
                        if not any(d['url'] == full_url for d in new_data):
                            new_data.append({
                                'title': title,
                                'url': full_url,
                                'scraped_at': today,
                                'location': location
                            })
            except:
                continue
                
    except Exception as e:
        print(f"❌ 에러: {e}")
    finally:
        driver.quit()
            
    print(f"🎯 수집된 공고: {len(new_data)}개")
    return new_data

def update_sheet(worksheet, data):
    all_values = worksheet.get_all_values()
    
    if not all_values:
        print("⚠️ 시트가 비어있습니다. 헤더를 생성합니다.")
        headers = ['title', 'url', 'scraped_at', 'status', 'location']
        worksheet.append_row(headers)
        all_values = [headers]
    
    headers = all_values[0]

    try:
        idx_title = headers.index('title')
        idx_url = headers.index('url')
        idx_scraped_at = headers.index('scraped_at')
        idx_status = headers.index('status')
        idx_location = headers.index('location')
    except ValueError as e:
        print(f"⛔ 헤더 오류: 1행에 {e} 컬럼이 있어야 합니다.")
        return

    existing_urls = set()
    for row in all_values[1:]:
        if len(row) > idx_url:
            existing_urls.add(row[idx_url])

    rows_to_append = []
    for item in data:
        if item['url'] in existing_urls:
            continue
            
        new_row = [''] * len(headers)
        new_row[idx_title] = item['title']
        new_row[idx_url] = item['url']
        new_row[idx_scraped_at] = item['scraped_at']
        new_row[idx_status] = 'archived'
        new_row[idx_location] = item['location']
        
        rows_to_append.append(new_row)

    if rows_to_append:
        print(f"📝 데이터 쓰기 시작... (총 {len(rows_to_append)}건)")
        worksheet.append_rows(rows_to_append)
        print(f"💾 저장 완료!")
    else:
        print("ℹ️ 새로운 공고 없음.")

if __name__ == "__main__":
    try:
        sheet = get_google_sheet()
        projects = get_projects()
        update_sheet(sheet, projects)
    except Exception as e:
        print(f"🚨 실행 실패: {e}")
