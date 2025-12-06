import requests
from bs4 import BeautifulSoup
import re
import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

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
            
            new_data.append({
                'title': title,
                'url': full_url,
                'created_at': today
            })
            
    return new_data

def update_sheet(worksheet, data):
    all_values = worksheet.get_all_values()
    if not all_values:
        print("시트가 비어있습니다. 1행에 헤더를 넣어주세요.")
        return

    headers = all_values[0]
    
    # 컬럼 위치 찾기 (status 추가됨)
    try:
        idx_title = headers.index('title')
        idx_url = headers.index('url')
        idx_created_at = headers.index('created_at')
        idx_status = headers.index('status') # status 컬럼 위치 찾기
    except ValueError:
        print("오류: 시트 1행에 'title', 'url', 'created_at', 'status' 컬럼이 정확히 있어야 합니다.")
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
        new_row[idx_status] = 'archived'  # 여기에 'archived' 값 고정 입력
        
        rows_to_append.append(new_row)

    if rows_to_append:
        worksheet.append_rows(rows_to_append)
        print(f"총 {len(rows_to_append)}개의 새로운 프로젝트를 추가했습니다.")
    else:
        print("새로운 공고가 없습니다.")

if __name__ == "__main__":
    try:
        sheet = get_google_sheet()
        projects = get_projects()
        update_sheet(sheet, projects)
    except Exception as e:
        print(f"에러 발생: {e}")
