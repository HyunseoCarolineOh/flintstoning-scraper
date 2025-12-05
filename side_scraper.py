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
# 3. 사이드 프로젝트 수집 (필터링 대폭 완화)
# ==========================================
print("▶ 사이드 프로젝트 접속 중...")
driver.get("https://sideproject.co.kr/projects")
time.sleep(7) # 로딩 대기 시간 늘림

# 스크롤 내려서 데이터 확보
for _ in range(3):
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)

side_data = []
all_links = driver.find_elements(By.TAG_NAME, "a")

print(f"🔎 발견된 전체 링크 수: {len(all_links)}개")

for link in all_links:
    try:
        url = link.get_attribute("href")
        title = link.text.strip()
        
        # [수정됨] URL 규칙 검사 삭제!
        # 그냥 제목이 7글자 이상이고, 메뉴(로그인 등)가 아니면 무조건 수집
        if url and title and len(title) > 7:
            
            # 메뉴나 불필요한 링크 제외
            ignore_words = ["로그인", "회원가입", "마이페이지", "공지사항", "이용약관", "개인정보", "비밀번호", "글쓰기"]
            if any(word in title for word in ignore_words):
                continue
            
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
                # 로그에 찍어서 확인
                if len(side_data) <= 3:
                    print(f"   🆕 수집 후보: {title[:15]}... ({url})")
    except:
        continue

print(f"✅ 최종 수집 개수: {len(side_data)}개")

# ▼▼▼ 시트 주소 확인 ▼▼▼
sheet_url = '여기에_구글_시트_주소를_넣으세요'
save_to_sheet(sheet_url, side_data)

driver.quit()
