import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

# =========================================================
# [설정] 시트 헤더 이름 설정 (이 부분을 실제 시트와 맞춰주세요)
# =========================================================
SHEET_NAME = '플린트스토닝 소재 DB'
COL_TITLE = 'title'      # 제목 컬럼 헤더명
COL_URL = 'url'          # URL 컬럼 헤더명
COL_STATUS = 'status'    # 상태 컬럼 헤더명 (기존 F열)
COL_PUBLISH = 'publish'  # 발행 여부 컬럼 헤더명

# =========================================================
# 1. 설정 및 인증
# =========================================================
try:
    print("--- [Side Sender] 시작 ---")
    
    json_creds = os.environ['GOOGLE_CREDENTIALS']
    creds_dict = json.loads(json_creds)
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    spreadsheet = client.open(SHEET_NAME) 
    sheet = spreadsheet.sheet1

    # 데이터 가져오기
    data = sheet.get_all_values()
    if not data:
        print("❌ 데이터가 없습니다.")
        exit()

    headers = data.pop(0)
    df = pd.DataFrame(data, columns=headers)

    # =========================================================
    # 2. 필터링 (Status: archived, Publish: TRUE)
    # =========================================================
    
    # 필수 헤더 존재 여부 확인
    required_cols = [COL_TITLE, COL_URL, COL_STATUS, COL_PUBLISH]
    for col in required_cols:
        if col not in df.columns:
            print(f"❌ 오류: 시트에 '{col}' 헤더가 없습니다. 헤더 이름을 확인해주세요.")
            exit()

    # 조건 확인 (공백 제거 후 비교)
    condition = (df[COL_STATUS].str.strip() == 'archived') & (df[COL_PUBLISH].str.strip() == 'TRUE')
    target_rows = df[condition]

    if target_rows.empty:
        print("ℹ️ 발송할 대상(archived & publish=TRUE)이 없습니다.")
        exit()

    # 첫 번째 행 선택
    row = target_rows.iloc[0]
    
    # 행 번호 계산 (헤더 1줄 + 0-based index 보정 = +2)
    update_row_index = row.name + 2
    
    # 상태 업데이트를 위한 열 번호 계산 (헤더 리스트에서 인덱스 찾기 + 1)
    # 이렇게 하면 열이 이동해도 헤더 이름만 같다면 안전합니다.
    status_col_index = headers.index(COL_STATUS) + 1

    project_title = row[COL_TITLE]
    target_url = row[COL_URL]
    
    print(f"▶ 선택된 행: {update_row_index}")
    print(f"▶ 제목: {project_title}")
    print(f"▶ URL: {target_url}")

    # =========================================================
    # 3. 웹 스크래핑
    # =========================================================
    print("--- 스크래핑 시작 ---")
    headers_ua = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    try:
        response = requests.get(target_url, headers=headers_ua, timeout=15)
        response.raise_for_status() # 4xx, 5xx 에러 시 예외 발생

        soup = BeautifulSoup(response.text, 'html.parser')
        paragraphs = soup.find_all('p')
        full_text = " ".join([p.get_text() for p in paragraphs])
        
        if len(full_text) < 50:
            # P 태그가 없거나 내용이 너무 짧은 경우 (동적 페이지 등)
            full_text = soup.get_text() # 전체 텍스트 긁기 시도

        truncated_text = full_text[:3000].strip()
        
        if not truncated_text:
            raise Exception("본문 내용을 추출할 수 없습니다.")

    except Exception as e:
        print(f"❌ 스크래핑 실패: {e}")
        # 스크래핑 실패 시 여기서 종료하거나, 슬랙으로 에러 메시지를 보낼 수 있습니다.
        exit()

    # =========================================================
    # 4. GPT 요약
    # =========================================================
    print("--- GPT 요약 요청 ---")
    client_openai = OpenAI(api_key=os.environ['OPENAI_API_KEY'])

    gpt_prompt = f"""
    너는 채용 공고나 프로젝트 정보를 정리해주는 '전문 에디터'야.
    아래 [글 내용]을 읽고, 지정된 **출력 양식**을 엄격하게 지켜서 답변해.
    모든 텍스트에 이모지를 절대 사용하지 마.

    [출력 양식]

    *이런 분께 추천해요*
    - (추천 대상 1)
    - (추천 대상 2)

    [글 내용]
    {truncated_text}
    """

    completion = client_openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a strict output formatter. Do not use emojis."},
            {"role": "user", "content": gpt_prompt}
        ]
    )

    gpt_body = completion.choices[0].message.content

    final_message = f"*추천 프로젝트*\n<{target_url}|{project_title}>\n\n{gpt_body}"
    final_message_with_link = f"{final_message}\n\n🔗 <{target_url}|모집공고 바로가기>"
    
    print("--- 최종 결과물 생성 완료 ---")

    # =========================================================
    # 5. 슬랙 전송 & 시트 업데이트
    # =========================================================
    print("--- 슬랙 전송 시작 ---")
    
    webhook_url = os.environ['SLACK_WEBHOOK_URL']
    payload = {"text": final_message_with_link}
    
    slack_res = requests.post(webhook_url, json=payload)
    
    if slack_res.status_code == 200:
        print("✅ 슬랙 전송 성공!")
        
        try:
            print(f"▶ 시트 상태 업데이트 중... (행: {update_row_index}, 열: {status_col_index})")
            # 헤더 이름으로 찾은 정확한 열 위치 업데이트
            sheet.update_cell(update_row_index, status_col_index, 'published')
            print("✅ 상태 변경 완료 (archived -> published)")
        except Exception as e:
            print(f"⚠️ 상태 업데이트 실패: {e}")
            # 참고: 업데이트 실패해도 슬랙은 이미 갔으므로 치명적이지 않음
            
    else:
        print(f"❌ 전송 실패 (상태 코드: {slack_res.status_code})")
        print(slack_res.text)

except Exception as e:
    print(f"\n❌ 치명적 에러 발생: {e}")
