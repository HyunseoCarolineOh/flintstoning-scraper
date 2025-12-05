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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
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
            print(f"[사이드] {len(final_data)}개 저장 완료!")
        else:
            print("[사이드] 새로운 데이터가 없습니다.")
            
    except Exception as e:
        print(f"[사이드] 저장 실패: {e}")

# ==========================================
# 2. 브라우저 설정 (강화됨)
# ==========================================
options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
# 최신 맥북 크롬으로 위장
options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
options.add_argument("--window-size=1920,1080")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
today_date = datetime.now().strftime('%Y-%m-%d')

# ==========================================
# 3. 사이드 프로젝트 수집 (대기 로직 추가)
# ==========================================
print("▶ 사이드 프로젝트 접속 중...")
driver.get("https://sideproject.co.kr/projects")

# [핵심] 데이터가 로딩될 때까지 최대 20초 기다림
try:
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.TAG_NAME, "a"))
    )
    print("✅ 사이트 로딩 성공!")
except:
    print("⚠️ 로딩 시간 초과 (그래도 진행해봅니다)")

time.sleep(5)

# 스크롤 3번 강하게 내리기
for _ in range(3):
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(3)

side_data = []
all_links = driver.find_elements(By.TAG_NAME, "a")

print(f"🔎 발견된 전체 링크 수: {len(all_links)}개")

for link in all_links:
    try:
        url = link.get_attribute("href")
        title = link.text.strip()
        
        # 제목이 있고, 길이가 7자 이상인 것만
        if url and title and len(title) > 7:
            # 제외 단어 필터링
            ignore_words = ["로그인", "회원가입", "마이페이지", "공지사항", "이용약관", "개인정보", "비밀번호", "글쓰기"]
            if any(word in title for word in ignore_words):
                continue
            
            # 리스트 중복 방지
            if not any(d['url'] == url for d in side_data):
                side_data.append({
                    'title': title,
                    'subtitle': '',
                    'url': url,
                    'created_at': today_date,
                    'company': '',
                    'status': 'archived',
                    'publish': ''
                })
    except:
        continue

print(f"✅ 최종 수집 개수: {len(side_data)}개")

# ▼▼▼ 시트 주소 확인 ▼▼▼
sheet_url = 'https://docs.google.com/spreadsheets/d/1nKPVCZ6zAOfpqCjV6WfjkzCI55FA9r2yvi9XL3iIneo/edit?gid=1818966683#gid=1818966683'
save_to_sheet(sheet_url, side_data)

driver.quit()
