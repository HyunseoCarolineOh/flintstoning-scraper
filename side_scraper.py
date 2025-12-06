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
TARGET_GID = 1818966683
SCRAPE_URL = "https://sideproject.co.kr/projects"

def get_google_sheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(os.environ['GOOGLE_CREDENTIALS'])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    spreadsheet = client.open_by_url(SHEET_URL)
    worksheet = None
    
    for sheet in spreadsheet.worksheets():
        if sheet.id == TARGET_GID:
            worksheet = sheet
            break
            
    if worksheet is None:
        raise Exception(f"GID가 {TARGET_GID}인 시트를 찾을 수 없습니다.")
    return worksheet

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # [중요] 봇 탐지 방지를 위한 가짜 User-Agent 설정
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    chrome_options.add_argument(f'user-agent={user_agent}')
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def get_projects():
    driver = get_driver()
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        driver.get(SCRAPE_URL)
        
        # [중요] 무작정 기다리는 게 아니라, 'a.post_link' 요소가 나올 때까지 최대 15초 대기
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a.post_link"))
            )
        except:
            print("대기 시간 초과: 게시물을 찾을 수 없습니다. 페이지 소스를 확인합니다.")
            print(driver.page_source[:500]) # 디버깅용: HTML 앞부분 출력

        # 게시물 찾기
        articles = driver.find_elements(By.CSS_SELECTOR, "a.post_link")
        print(f"웹사이트에서 발견한 게시물 수: {len(articles)}")

        for article in articles:
            try:
                title = article.text.strip()
                raw_link = article.get_attribute("href")
                
                idx_match = re.search(r'idx=(\d+)', raw_link)
                if idx_match:
                    idx = idx_match.group(1)
                    full_url = f"https://sideproject.co.kr/projects/?bmode=view&idx={idx}"
                    
                    new_data.append({
                        'title': title,
                        'url': full_url,
                        'created_at': today
                    })
            except Exception as inner_e:
                continue
                
    except Exception as e:
        print(f"크롤링 중 에러: {e}")
    finally:
        driver.quit()
            
    return new_data

def update_sheet(worksheet, data):
    all_values = worksheet.get_all_values()
    
    if not all_values: # 시트가 비었을 때
        headers = [] 
    else:
        headers = all_values[0]
    
    try:
        idx_title = headers.index('title')
        idx_url = headers.index('url')
        idx_created_at = headers.index('created_at')
        idx_status = headers.index('status')
    except ValueError:
        print("오류: 시트 1행 헤더(title, url, created_at, status)를 찾을 수 없습니다.")
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
        new_row[idx_status] = 'archived'
        
        rows_to_append.append(new_row)

    if rows_to_append:
        worksheet.append_rows(rows_to_append)
        print(f"{len(rows_to_append)}개 추가 완료.")
    else:
        print("새로운 공고가 없습니다 (이미 수집했거나 데이터를 못 찾음).")

if __name__ == "__main__":
    try:
        sheet = get_google_sheet()
        projects = get_projects()
        update_sheet(sheet, projects)
    except Exception as e:
        print(f"실행 에러: {e}")
