import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import time

# =========================================================
# 1. 설정 및 인증
# =========================================================
try:
    print("--- [Insight Sender] 시작 ---")

    # 환경변수에서 키 로드 (보안 유지)
    json_creds = os.environ.get('GOOGLE_CREDENTIALS')
    if not json_creds:
        raise ValueError("❌ GOOGLE_CREDENTIALS 환경 변수가 설정되지 않았습니다.")
        
    creds_dict = json.loads(json_creds)
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    # 시트 열기
    spreadsheet = client.open('플린트스토닝 소재 DB')
    sheet = spreadsheet.get_worksheet(1) # 두 번째 탭

    # 데이터 가져오기
    data = sheet.get_all_values()
    if not data:
        print("❌ 데이터가 없습니다.")
        exit()

    headers = data.pop(0)
    df = pd.DataFrame(data, columns=headers)

    # =========================================================
    # 2. 필터링 로직 개선 (헤더 이름 사용 권장)
    # =========================================================
    
    # [설정] 실제 시트의 헤더 이름과 정확히 일치해야 합니다.
    # 만약 헤더 이름이 자주 바뀐다면 기존처럼 인덱스를 써야 하지만, 
    # 아래처럼 변수로 관리하는 것이 유지보수에 좋습니다.
    COL_TITLE = headers[0]    # A열 (보통 'Title' 또는 '제목')
