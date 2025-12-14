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
TARGET_GID = 1669656972 
SCRAPE_URL = "https://letspl.me/project?location=KR00&type=00&recruitingType=all&jobD=0207&skill=&interest=&keyword="

# [수정됨] 감지할 지역 키워드 리스트 정의
REGION_KEYWORDS = [
    "서울", "경기", "인천", "대전", "대구", "부산", "광주", "울산", "세종", 
    "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주", "온라인"
]

def get_google_sheet():
    # ... (기존과 동일)
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
    # ... (기존과 동일)
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
        print("🌐 Letspl 접속 중...")
        driver.get(SCRAPE_URL)
        
        wait = WebDriverWait(driver, 15)
        # 프로젝트 카드가 로딩될 때까지 대기
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/project/']")))
        
        time.sleep(3) # 안정적인 로딩을 위해 잠시 대기
        
        elements = driver.find_elements(By.CSS_SELECTOR, "a[href^='/project/']")
        print(f"🔍 발견된 프로젝트 링크 수: {len(elements)}개")

        for elem in elements:
            try:
                full_url = elem.get_attribute("href")
                
                # URL 유효성 검사 (프로젝트 상세 페이지 링크가 맞는지)
                if not re.search(r'/project/\d+', full_url):
                    continue
                
                # ==========================================
                # [핵심 수정] 제목만 정확하게 핀셋으로 집어내기
                # ==========================================
                title = ""
                try:
                    # 렛플 사이트 구조상 제목은 보통 h3, h4, 또는 tit 클래스를 가진 요소에 있습니다.
                    # '팔로우' 버튼이나 설명글은 이 태그 안에 들어있지 않으므로 자연스럽게 걸러집니다.
                    title_elem = elem.find_element(By.CSS_SELECTOR, "h3, h4, div.tit, strong")
                    title = title_elem.text.strip()
                except:
                    # 혹시 태그로 못 찾을 경우를 대비한 비상 대책
                    pass

                # 비상 대책: 태그로 못 찾았거나 제목이 비어있다면 텍스트 필터링 시도
                if not title:
                    raw_text = elem.text
                    lines = raw_text.split('\n')
                    # '팔로우', '모집' 등이 들어간 줄은 무조건 제외
                    clean_lines = [
                        line.strip() for line in lines 
                        if len(line.strip()) > 1 
                        and "팔로우" not in line 
                        and "모집" not in line
                        and "스크랩" not in line
                    ]
                    # 남은 줄 중 첫 번째 줄을 제목으로 간주
                    if clean_lines:
                        title = clean_lines[0]
                    else:
                        title = "제목 없음"

                # ==========================================
                # [기존 유지] 지역 정보 추출 로직
                # ==========================================
                location = "미정"
                # 전체 텍스트에서 지역 키워드 찾기
                full_text = elem.text 
                for keyword in REGION_KEYWORDS:
                    if keyword in full_text:
                        location = keyword
                        break

                # 데이터 저장 (제목이 2글자 이상인 경우만)
                if len(title) > 1:
                    if not any(d['url'] == full_url for d in new_data):
                        new_data.append({
                            'title': title,
                            'url': full_url,
                            'scraped_at': today,
                            'location': location
                        })
                        
            except Exception as e:
                # 개별 항목 에러는 무시하고 다음으로 진행
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
        # 헤더가 아예 없는 경우 생성
        headers = ['title', 'url', 'scraped_at', 'status', 'location']
        worksheet.append_row(headers)
        all_values = [headers]
    
    headers = all_values[0]

    try:
        idx_title = headers.index('title')
        idx_url = headers.index('url')
        idx_scraped_at = headers.index('scraped_at')
        idx_status = headers.index('status')
        # [수정됨] location 컬럼 인덱스 찾기
        idx_location = headers.index('location') 
    except ValueError as e:
        print(f"⛔ 헤더 오류: 시트 1행에 {e} 컬럼이 있어야 합니다.")
        print("💡 팁: 구글 시트 1행에 'location' 이라고 적힌 셀을 추가해주세요.")
        return

    existing_urls = set()
    for row in all_values[1:]:
        if len(row) > idx_url:
            existing_urls.add(row[idx_url])

    rows_to_append = []
    for item in data:
        if item['url'] in existing_urls:
            continue
            
        # 빈 행 생성 (헤더 길이만큼)
        new_row = [''] * len(headers)
        
        # 값 매핑
        new_row[idx_title] = item['title']
        new_row[idx_url] = item['url']
        new_row[idx_scraped_at] = item['scraped_at']
        new_row[idx_status] = 'archived'
        new_row[idx_location] = item['location'] # [수정됨] 지역 값 입력
        
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
