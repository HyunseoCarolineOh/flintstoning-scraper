import requests
from bs4 import BeautifulSoup
import re
import os
import json
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials

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

def get_projects():
    # [핵심] 봇 차단을 피하기 위해 '사람인 척'하는 헤더 추가
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    print("사이트에 접속을 시도합니다...")
    response = requests.get(SCRAPE_URL, headers=headers)
    
    # 접속 상태 확인
    if response.status_code != 200:
        print(f"접속 실패! 상태 코드: {response.status_code}")
        return []

    print(f"접속 성공! 데이터 길이: {len(response.text)}")
    soup = BeautifulSoup(response.text, 'html.parser')
    
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")

    # 모든 링크(a 태그)를 다 가져와서 검사
    links = soup.find_all('a')
    print(f"발견된 전체 링크 수: {len(links)}")

    for link in links:
        raw_link = link.get('href')
        title = link.get_text(strip=True)

        # 링크가 있고, idx= 숫자가 포함된 주소라면 공고로 판단
        if raw_link and 'idx=' in raw_link and 'bmode=view' in raw_link:
            # 제목이 너무 짧거나 없는 건 제외 (아이콘 등)
            if not title:
                continue

            # idx 추출
            idx_match = re.search(r'idx=(\d+)', raw_link)
            if idx_match:
                idx = idx_match.group(1)
                full_url = f"https://sideproject.co.kr/projects/?bmode=view&idx={idx}"
                
                # 중복 수집 방지 (현재 리스트 내에서)
                if not any(d['url'] == full_url for d in new_data):
                    new_data.append({
                        'title': title,
                        'url': full_url,
                        'created_at': today
                    })

    print(f"걸러낸 실제 공고 수: {len(new_data)}")
    return new_data

def update_sheet(worksheet, data):
    all_values = worksheet.get_all_values()
    if not all_values: headers = []
    else: headers = all_values[0]

    try:
        idx_title = headers.index('title')
        idx_url = headers.index('url')
        idx_created_at = headers.index('created_at')
        idx_status = headers.index('status')
    except ValueError:
        print("오류: 시트 헤더(title, url, created_at, status)가 정확하지 않습니다.")
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
        print(f"✅ {len(rows_to_append)}개의 새로운 공고를 시트에 저장했습니다!")
    else:
        print("ℹ️ 저장할 새로운 공고가 없습니다 (이미 다 저장됨).")

if __name__ == "__main__":
    try:
        sheet = get_google_sheet()
        projects = get_projects()
        update_sheet(sheet, projects)
    except Exception as e:
        print(f"🚨 에러 발생: {e}")
