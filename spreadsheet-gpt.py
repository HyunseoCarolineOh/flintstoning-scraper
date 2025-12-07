import os
import json
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup

# --- 환경 변수 로드 ---
# GitHub Secrets에 저장된 값들
GOOGLE_JSON = json.loads(os.environ['GOOGLE_SHEET_KEY'])
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
SLACK_WEBHOOK_URL = os.environ['SLACK_WEBHOOK_URL']
SHEET_URL = os.environ['SHEET_URL']

def get_sheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_JSON, scope)
    return gspread.authorize(creds)

def process_sheet():
    client = get_sheet_client()
    sheet = client.open_by_url(SHEET_URL).sheet1
    
    # get_all_records는 헤더를 키로 갖는 리스트를 반환
    data = sheet.get_all_records()
    
    target_row_index = None
    target_row_data = None
    
    # 1. 조건 검색: publish=TRUE AND status=archived
    # gspread 데이터는 0부터 시작하지만, 시트 행 번호(row_index)는 2부터 시작 (1행은 헤더)
    for i, row in enumerate(data):
        # 대소문자 구분 없이 문자열로 변환하여 체크
        if str(row.get('publish')).upper() == 'TRUE' and row.get('status') == 'archived':
            target_row_index = i + 2 
            target_row_data = row
            break # 1행만 처리하므로 찾으면 즉시 중단
            
    if not target_row_data:
        print("📭 조건(publish=TRUE, status=archived)에 맞는 행이 없습니다.")
        return

    print(f"🚀 처리 시작: 행 {target_row_index} - {target_row_data.get('url')}")
    
    # 2. URL 내용 가져오기
    url = target_row_data.get('url')
    content = fetch_url_content(url)
    
    if not content:
        print("❌ URL 내용을 가져오지 못했습니다.")
        # 실패 시 status를 error로 바꾸는 로직을 추가할 수도 있음
        return

    # 3. Gemini 요약
    summary = summarize_with_gemini(content)
    
    # 4. Slack 전송
    send_slack_message(summary, url)
    
    # 5. 상태 업데이트 (중복 방지 핵심 로직)
    # 'status' 컬럼이 몇 번째 열인지 찾아서 업데이트 (보통 헤더가 1행에 있다고 가정)
    headers = sheet.row_values(1)
    try:
        status_col_index = headers.index('status') + 1 # 리스트 인덱스는 0부터, 시트 열은 1부터
        sheet.update_cell(target_row_index, status_col_index, 'done')
        print(f"✅ 상태 업데이트 완료: 행 {target_row_index} -> 'done'")
    except ValueError:
        print("⚠️ 'status' 컬럼을 찾을 수 없어 상태를 업데이트하지 못했습니다.")

def fetch_url_content(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 불필요한 태그 제거
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
            
        text = soup.get_text(separator=' ')
        # 공백 정리 및 길이 제한
        clean_text = ' '.join(text.split())
        return clean_text[:8000] # Gemini 입력 제한 고려
    except Exception as e:
        print(f"URL Fetch Error: {e}")
        return None

def summarize_with_gemini(text):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
        당신은 전문 콘텐츠 큐레이터입니다. 아래 글을 읽고 다음 형식으로 슬랙 메시지를 작성해주세요.
        
        1. **3줄 요약**: 핵심 내용을 명확하게 요약 (이모지 활용)
        2. **Insight**: 이 글이 업무나 업계에 주는 시사점 한 문장
        
        [글 내용]
        {text}
        """
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini Error: {e}"

def send_slack_message(message, url):
    payload = {
        "text": f"🤖 *Daily Pick*\n{message}\n\n🔗 <{url}|원문 보러가기>"
    }
    requests.post(SLACK_WEBHOOK_URL, json=payload)

if __name__ == "__main__":
    process_sheet()
