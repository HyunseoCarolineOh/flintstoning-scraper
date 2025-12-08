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

    json_creds = os.environ['GOOGLE_CREDENTIALS']
    creds_dict = json.loads(json_creds)
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    # 시트 열기
    spreadsheet = client.open('플린트스토닝 소재 DB')
    
    # [체크] 두 번째 탭(Sheet2) 선택
    sheet = spreadsheet.get_worksheet(1) 

    # 데이터 가져오기
    data = sheet.get_all_values()
    if not data:
        print("❌ 데이터가 없습니다.")
        exit()

    headers = data.pop(0)
    df = pd.DataFrame(data, columns=headers)

    # =========================================================
    # 2. 필터링 (F열: archived, publish: TRUE)
    # =========================================================
    
    # [안전 장치] 최소 열 개수 확인
    if len(df.columns) < 6:
        print("❌ 열 개수가 부족합니다 (최소 6열 필요).")
        exit()

    col_status = df.columns[5] # F열 (0부터 시작하므로 인덱스 5)
    
    # 조건 확인 (archived & TRUE)
    # 대소문자나 공백 실수를 방지하기 위해 strip() 사용
    condition = (df[col_status].str.strip() == 'archived') & (df['publish'].str.strip() == 'TRUE')
    target_rows = df[condition]

    if target_rows.empty:
        print("ℹ️ 발송할 대상(archived & publish=TRUE)이 없습니다.")
        exit()

    # 첫 번째 행 선택
    row = target_rows.iloc[0]
    
    # 행 번호 계산 (헤더 1줄 + 0-based index 보정 = +2)
    update_row_index = row.name + 2
    
    print(f"▶ 선택된 행 번호: {update_row_index}")

    # =========================================================
    # 3. 데이터 추출 (A열: 제목, C열: URL)
    # =========================================================
    
    # [수정] A열(인덱스 0) -> 제목
    article_title = row.iloc[0]
    
    # [수정] C열(인덱스 2) -> URL
    target_url = row.iloc[2]

    # URL 유효성 간단 체크
    if not target_url or not target_url.startswith('http'):
        print(f"❌ URL 형식이 올바르지 않습니다: {target_url}")
        exit()

    print(f"▶ 제목: {article_title}")
    print(f"▶ URL: {target_url}")

    # =========================================================
    # 4. 웹 스크래핑
    # =========================================================
    print("--- 스크래핑 시작 ---")
    headers_ua = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML
