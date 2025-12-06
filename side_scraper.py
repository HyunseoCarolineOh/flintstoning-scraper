import requests
from bs4 import BeautifulSoup
import re
import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# 설정
SHEET_URL = "https://docs.google.com/spreadsheets/d/1nKPVCZ6zAOfpqCjV6WfjkzCI55FA9r2yvi9XL3iIneo/edit"
TARGET_GID = 1818966683  # 저장하려는 시트의 GID (탭 ID)
SCRAPE_URL = "https://sideproject.co.kr/projects"

def get_google_sheet():
    # 깃허브 시크릿에서 키 파일을 생성하여 인증
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(os.environ['GOOGLE_CREDENTIALS'])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    # 스프레드시트 열기
    spreadsheet = client.open_by_url(SHEET_URL)
    
    # GID로 특정 워크시트(탭) 찾기
    worksheet = None
    for sheet in spreadsheet.worksheets():
        if sheet.id == TARGET_GID:
            worksheet = sheet
            break
    
    if worksheet is None:
        raise Exception(f"GID가 {TARGET_GID}인 시트를 찾을 수 없습니다.")
        
    return worksheet

def get_projects():
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(SCRAPE_URL, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    articles = soup.select('a.post_link') 
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")

    for article in articles:
        title = article.get_text(strip=True)
        raw_link = article.get('href', '')
        idx_match = re.search(r'idx=(\d+)', raw_link)
        
        if idx_match:
            idx = idx_match.group(1)
            full_url = f"https://sideproject.co.kr/projects/?bmode=view&idx={idx}"
            new_data.append({'date': today, 'title': title, 'url': full_url})
            
    return new_data

def update_sheet(worksheet, data):
    # 모든 데이터 가져오기 (헤더 포함)
    all_values = worksheet.get_all_values()
    
    if not all_values:
        print("시트가 비어있습니다. 헤더를 먼저 확인해주세요.")
        return

    headers = all_values[0] # 첫 번째 줄을 헤더로 가정
    
    # 컬럼 인덱스 찾기 (0부터 시작)
    try:
        col_title = headers.index('title')
        col_url = headers.index('url')
        # 날짜 컬럼이 있다면 찾고, 없으면 맨 앞에 넣거나 무시 (여기선 맨 앞이 좋음)
        try:
            col_date = headers.index('date')
        except ValueError:
            col_date = -1 # 날짜 컬럼 없음
    except ValueError:
        print("오류: 시트의 1행에 'title' 또는 'url' 헤더가 정확히 적혀있어야 합니다.")
        return

    # 기존 URL 수집 (중복 방지)
    existing_urls = set()
    for row in all_values[1:]:
        if len(row) > col_url:
            existing_urls.add(row[col_url])

    # 추가할 행 준비
    rows_to_append = []
    for item in data:
        if item['url'] not in existing_urls:
            # 빈 행 생성 (헤더 길이만큼)
            new_row = [''] * len(headers)
            
            # 값 채우기
            new_row[col_title] = item['title']
            new_row[col_url] = item['url']
            if col_date != -1:
                new_row[col_date] = item['date']
            
            rows_to_append.append(new_row)

    if rows_to_append:
        worksheet.append_rows(rows_to_append)
        print(f"{len(rows_to_append)}개의 새로운 공고를 시트에 추가했습니다.")
    else:
        print("새로운 공고가 없습니다.")

if __name__ == "__main__":
    try:
        sheet = get_google_sheet()
        projects = get_projects()
        update_sheet(sheet, projects)
    except Exception as e:
        print(f"에러 발생: {e}")
