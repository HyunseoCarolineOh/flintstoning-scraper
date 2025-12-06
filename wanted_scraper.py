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
# ▼ 원티드 탭 GID (확인 필수)
TARGET_GID = 639559541 
SCRAPE_URL = "https://www.wanted.co.kr/wdlist/523/1635?country=kr&job_sort=job.popularity_order&years=-1&locations=all"

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
    
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    chrome_options.add_argument(f"user-agent={user_agent}")
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def get_projects():
    driver = get_driver()
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        print("🌐 원티드(Wanted) 접속 중...")
        driver.get(SCRAPE_URL)
        
        time.sleep(5)
        driver.execute_script("window.scrollTo(0, 1000);")
        time.sleep(3)
        
        elements = driver.find_elements(By.TAG_NAME, "a")
        print(f"🔍 페이지 내 전체 링크 수: {len(elements)}개")

        for elem in elements:
            try:
                full_url = elem.get_attribute("href")
                if not full_url or "/wd/" not in full_url:
                    continue
                
                raw_text = elem.text.strip()
                if not raw_text: continue

                # [텍스트 분석]
                lines = raw_text.split('\n')
                
                # 1. 불필요한 정보(보상금, 뱃지 등) 제거
                safe_lines = []
                for line in lines:
                    text = line.strip()
                    if not text: continue
                    
                    if "합격보상금" in text or "보상금" in text: continue
                    if text.endswith("원") and any(c.isdigit() for c in text): continue 
                    if "응답률" in text or "입사축하금" in text: continue
                    
                    safe_lines.append(text)
                
                # 2. 남은 줄 분석 (제목, 회사명 추출)
                if len(safe_lines) >= 2:
                    title = safe_lines[0]    # 첫 번째 줄 = 제목
                    company = safe_lines[1]  # 두 번째 줄 = 회사명
                    
                    idx_match = re.search(r'/wd/(\d+)', full_url)
                    if len(title) > 2 and idx_match:
                        
                        if not any(d['url'] == full_url for d in new_data):
                            new_data.append({
                                'title': title,
                                'company': company,
                                'url': full_url,
                                'created_at': today
                            })
            except:
                continue
                
    except Exception as e:
        print(f"❌ 에러 발생: {e}")
    finally:
        driver.quit()
            
    print(f"🎯 수집된 공고: {len(new_data)}개")
    return new_data

def update_sheet(worksheet, data):
    all_values = worksheet.get_all_values()
    
    if not all_values:
        headers = []
    else:
        headers = all_values[0]

    try:
        # [중요] 1행 헤더 이름을 보고 위치를 자동으로 찾습니다.
        # F1 셀에 'company'라고 적혀있으면 idx_company는 자동으로 5(F열)가 됩니다.
        idx_title = headers.index('title')
        idx_url = headers.index('url')
        idx_created_at = headers.index('created_at')
        idx_status = headers.index('status')
        idx_company = headers.index('company') 
    except ValueError:
        print("⛔ 헤더 오류: 시트 1행에 title, url, created_at, status, company 가 모두 있어야 합니다.")
        return

    existing_urls = set()
    for row in all_values[1:]:
