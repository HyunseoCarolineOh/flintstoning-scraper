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
TARGET_GID = 981623942  # Mix 탭 GID
SCRAPE_URL = "https://mix.day/"

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
    
    # 봇 차단 회피
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    chrome_options.add_argument(f"user-agent={user_agent}")
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def get_projects():
    driver = get_driver()
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        print("🌐 Mix.day 접속 중...")
        driver.get(SCRAPE_URL)
        
        # 화면 로딩 대기
        time.sleep(10)
        
        elements = driver.find_elements(By.TAG_NAME, "a")
        print(f"🔍 페이지 내 전체 링크 수: {len(elements)}개")

        for elem in elements:
            try:
                full_url = elem.get_attribute("href")
                
                # [수정됨] 텍스트 전체를 가져와서 분석
                raw_text = elem.text.strip()
                
                if not full_url or not raw_text:
                    continue
                
                # ----------------------------------------------------
                # [핵심] 제목만 쏙 골라내는 로직
                # 1. 줄바꿈(\n)을 기준으로 텍스트를 나눕니다.
                lines = raw_text.split('\n')
                
                # 2. 'Ambassador', '·'(날짜 구분자) 등이 포함된 줄은 버립니다.
                cleaned_lines = [
                    line.strip() for line in lines 
                    if "Ambassador" not in line       # 앰배서더 태그 제외
                    and "·" not in line               # 날짜/작성자 제외 (예: 믹스 · 1주전)
                    and len(line.strip()) > 0         # 빈 줄 제외
                ]
                
                # 3. 남은 줄 중에서 '가장 긴 줄'을 제목으로 선택합니다.
                # (보통 제목이 태그나 짧은 단어보다 깁니다)
                if cleaned_lines:
                    title = max(cleaned_lines, key=len)
                else:
                    title = raw_text # 정제 실패 시 원본 사용
                # ----------------------------------------------------

                # 필터링: 제목이 10글자 이상이고, http 링크인 경우만
                if len(title) > 10 and "http" in full_url:
                    
                    if not any(d['url'] == full_url for d in new_data):
                        # 메뉴 등 제외
                        if "로그인" in title or "회원가입" in title:
                            continue

                        new_data.append({
                            'title': title,
                            'url': full_url,
                            'created_at': today
                        })
            except:
                continue
                
    except Exception as e:
        print(f"❌ 에러 발생: {e}")
    finally:
        driver.quit()
            
    print(f"🎯 정제된 게시물: {len(new_data)}개")
    return new_data

def update_sheet(worksheet, data):
    all_values = worksheet.get_all_values()
    
    if not all_values:
        headers = []
    else:
        headers = all_values[0]

    try:
        idx_title = headers.index('title')
        idx_url = headers.index('url')
        idx_created_at = headers.index('created_at')
        idx_status = headers.index('status')
    except ValueError:
        print("⛔ 헤더 오류: 시트 1행에 title, url, created_at, status 가 있어야 합니다.")
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
        new_row[idx_created_at] = item['created_at']
        new_row[idx_status] = 'new'
        rows_to_append.append(new_row)

    if rows_to_append:
        worksheet.append_rows(rows_to_append)
        print(f"💾 {len(rows_to_append)}개 저장 완료!")
    else:
        print("ℹ️ 새로운 게시물이 없습니다.")

if __name__ == "__main__":
    try:
        sheet = get_google_sheet()
        projects = get_projects()
        update_sheet(sheet, projects)
    except Exception as e:
        print(f"🚨 실행 실패: {e}")
