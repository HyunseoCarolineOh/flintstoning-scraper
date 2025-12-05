import time
import json
import os
import pandas as pd
import gspread
from gspread_dataframe import set_with_dataframe, get_as_dataframe
from google.oauth2.service_account import Credentials
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium_stealth import stealth
from datetime import datetime
import random

# ==========================================
# 1. 구글 시트 인증
# ==========================================
json_creds = json.loads(os.environ['GOOGLE_CREDENTIALS'])
scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds = Credentials.from_service_account_info(json_creds, scopes=scope)
gc = gspread.authorize(creds)

def save_to_sheet(sheet_url, new_data):
    try:
        if 'gid=' in sheet_url:
            target_gid = int(sheet_url.split('gid=')[1].split('#')[0])
            doc = gc.open_by_url(sheet_url)
            worksheet = next((ws for ws in doc.worksheets() if ws.id == target_gid), None)
        else:
            doc = gc.open_by_url(sheet_url)
            worksheet = doc.get_worksheet(0)
            
        if not worksheet:
            print("[원티드] 탭을 찾을 수 없습니다.")
            return

        existing_df = get_as_dataframe(worksheet, header=0)
        existing_data_count = len(existing_df.dropna(how='all'))
        next_row = existing_data_count + 2
        
        try:
            existing_urls = worksheet.col_values(3)[1:]
        except:
            existing_urls = []

        final_data = []
        for item in new_data:
            if item['url'] not in existing_urls:
                final_data.append(item)
        
        if final_data:
            df = pd.DataFrame(final_data)
            set_with_dataframe(worksheet, df, row=next_row, include_column_header=False)
            print(f"[원티드] {len(final_data)}개 저장 완료!")
        else:
            print("[원티드] 새로운 데이터가 없습니다.")
            
    except Exception as e:
        print(f"[원티드] 저장 실패: {e}")

# ==========================================
# 2. 브라우저 설정
# ==========================================
options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

stealth(driver,
        languages=["ko-KR", "ko"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True)

today_date = datetime.now().strftime('%Y-%m-%d')

# ==========================================
# 3. 원티드 크롤링 (태그 정밀 타격)
# ==========================================
print("▶ 원티드 수집 시작")
driver.get("https://www.wanted.co.kr/wdlist/523/1635?country=kr&job_sort=job.popularity_order&years=-1&locations=all")
time.sleep(10)

for _ in range(5):
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(random.uniform(3, 5))
    
wanted_data = []

all_links = driver.find_elements(By.TAG_NAME, "a")
articles = [link for link in all_links if link.get_attribute("href") and "/wd/" in link.get_attribute("href")]

for article in articles:
    try:
        link = article.get_attribute("href")
        
        try:
            # 1. 제목 찾기
            title_tag = article.find_element(By.TAG_NAME, "strong")
            title = title_tag.text.strip()
            
            # 2. 회사명 찾기
            company_tag = article.find_element(By.CSS_SELECTOR, "span[class*='company']")
            company = company_tag.text.strip()
            
            if title and company:
                 wanted_data.append({
                    'title': title, 
                    'subtitle': '', 
                    'url': link, 
                    'created_at': today_date, 
                    'company': company, 
                    'status': 'archived', # [수정됨] active -> archived 변경
                    'publish': ''
                })
        except:
            continue
            
    except: continue

# ▼▼▼ [중요] 원티드 시트 주소 입력 ▼▼▼
wanted_url = 'https://docs.google.com/spreadsheets/d/1nKPVCZ6zAOfpqCjV6WfjkzCI55FA9r2yvi9XL3iIneo/edit?gid=1818966683#gid=1818966683'
save_to_sheet(wanted_url, wanted_data)

driver.quit()
