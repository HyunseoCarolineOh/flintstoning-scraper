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
from datetime import datetime

# ==========================================
# 1. 구글 시트 인증
# ==========================================
json_creds = json.loads(os.environ['GOOGLE_CREDENTIALS'])
scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds = Credentials.from_service_account_info(json_creds, scopes=scope)
gc = gspread.authorize(creds)

def save_to_sheet(sheet_url, new_data):
    try:
        # gid 추출 및 탭 연결
        if 'gid=' in sheet_url:
            target_gid = int(sheet_url.split('gid=')[1].split('#')[0])
            doc = gc.open_by_url(sheet_url)
            worksheet = next((ws for ws in doc.worksheets() if ws.id == target_gid), None)
        else:
            doc = gc.open_by_url(sheet_url)
            worksheet = doc.get_worksheet(0)
            
        if not worksheet:
            print("[사이드] 탭을 찾을 수 없습니다.")
            return

        # 위치 계산
        existing_df = get_as_dataframe(worksheet, header=0)
        existing_data_count = len(existing_df.dropna(how='all'))
        next_row = existing_data_count + 2
        
        # 중복 방지용 URL 확인
        try:
            existing_urls = worksheet.col_values(3)[1:] # C열(URL)
        except:
            existing_urls = []

        # 중복 제거
        final_data = []
        for item in new_data:
            if item['url'] not in existing_urls:
                final_data.append(item)
        
        if final_data:
            df = pd.DataFrame(final_data)
            # 헤더 없이 데이터만 추가
            set_with_dataframe(worksheet, df, row=next_row, include_column_header=False)
            print(f"[사이드] {len(final_data)}개 저장 완료!")
        else:
            print("[사이드] 새로운 데이터가 없습니다.")
            
    except Exception as e:
        print(f"[사이드] 저장 실패: {e}")

# ==========================================
# 2. 브라우저 설정
# ==========================================
options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
today_date = datetime.now().strftime('%Y-%m-%d')

# ==========================================
# 3. 사이드 프로젝트 수집 시작
# ==========================================
print("▶ 사이드 프로젝트 접속 중...")
target_url = "https://sideproject.co.kr/projects"
driver.get(target_url)
time.sleep(5)

side_data = []

# 게시글 링크(a 태그) 찾기
# 보통 게시판 형태는 a 태그 안에 제목이 있거나, a 태그가 제목을 감싸고 있음
all_links = driver.find_elements(By.CSS_SELECTOR, "a")

print(f"🔎 탐색된 링크: {len(all_links)}개")

for link in all_links:
    try:
        url = link.get_attribute("href")
        title = link.text.strip()
        
        # 유효성 검사
        # 1. URL이 있어야 하고
        # 2. 제목이 적당히 길어야 함 (메뉴 버튼 제외)
        # 3. '/projects/' 가 포함된 상세 페이지 링크여야 함
        if url and title and len(title) > 5 and "/projects/" in url:
            
            # 리스트에 중복으로 잡히는 경우가 있어서 확인
            if not any(d['url'] == url for d in side_data):
                side_data.append({
                    'title': title,      # A열: 제목
                    'subtitle': '',      # B열
                    'url': url,          # C열: 링크
                    'created_at': today_date, # D열
                    'company': '',       # E열: (요청하신대로 빈칸)
                    'status': 'archived', # F열: archived
                    'publish': ''        # G열
                })
    except:
        continue

print(f"✅ 수집된 데이터 후보: {len(side_data)}개")

# ▼▼▼ [중요] 데이터를 넣을 시트 주소를 입력하세요 ▼▼▼
sheet_url = 'https://docs.google.com/spreadsheets/d/1nKPVCZ6zAOfpqCjV6WfjkzCI55FA9r2yvi9XL3iIneo/edit?gid=1818966683#gid=1818966683'

save_to_sheet(sheet_url, side_data)

driver.quit()
