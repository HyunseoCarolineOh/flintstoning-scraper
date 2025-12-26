import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

# =========================================================
# 1. 설정 및 인증
# =========================================================
try:
    print("--- [Mix Sender] 프로세스 시작 ---")
    
    if 'GOOGLE_CREDENTIALS' not in os.environ:
        raise Exception("환경변수 GOOGLE_CREDENTIALS가 설정되지 않았습니다.")

    creds_dict = json.loads(os.environ['GOOGLE_CREDENTIALS'])
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    spreadsheet = client.open('플린트스토닝 소재 DB')
    sheet = spreadsheet.get_worksheet(2)
    
    data = sheet.get_all_values()
    headers = [h.strip() for h in data[0]]
    df = pd.DataFrame(data[1:], columns=headers)

    COL_STATUS = 'status'
    COL_PUBLISH = 'publish'
    COL_TITLE = 'title'
    COL_URL = 'url'

    # status가 'archived'인 모든 행 추출
    target_rows = df[df[COL_STATUS].str.strip().str.lower() == 'archived']

    if target_rows.empty:
        print("ℹ️ 'archived' 상태의 아티클이 없습니다.")
        exit()

    publish_col_idx = headers.index(COL_PUBLISH) + 1
    status_col_idx = headers.index(COL_STATUS) + 1
    client_openai = OpenAI(api_key=os.environ['OPENAI_API_KEY'])
    webhook_url = os.environ['SLACK_WEBHOOK_URL']

    # =========================================================
    # 2. 루프 시작: 적합한 아티클을 찾을 때까지 반복
    # =========================================================
    for index, row in target_rows.iterrows():
        update_row_index = int(index) + 2
        project_title = row[COL_TITLE]
        target_url = row[COL_URL]
        
        print(f"\n🔍 검토 중 ({update_row_index}행): {project_title}")

        try:
            # 웹 스크래핑
            headers_ua = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(target_url, headers=headers_ua, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            paragraphs = soup.find_all(['p', 'h2', 'h3'])
            text_content = " ".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 20])
            truncated_text = text_content[:3500]

            # 정체성 판단
            identity_prompt = f"""
            너는 문화예술 및 테크 미디어 'ANTIEGG'의 편집장이야. 
            아래 [글 내용]이 ANTIEGG의 정체성에 부합하는지 판단해줘.
            [글 내용]: {truncated_text}
            [출력 양식 (JSON)]: {{"is_appropriate": true/false, "reason": "문장"}}
            """
            check_res = client_openai.chat.completions.create(
                model="gpt-4o-mini",
                response_format={ "type": "json_object" },
                messages=[{"role": "system", "content": "You are a professional editor for ANTIEGG."},
                          {"role": "user", "content": identity_prompt}]
            )
            judgment = json.loads(check_res.choices[0].message.content)
            
            if not judgment.get("is_appropriate", False):
                print(f"⚠️ 부적합: {judgment.get('reason')}")
                sheet.update_cell(update_row_index, publish_col_idx, 'FALSE')
                continue # 다음 행으로 넘어감

            # 적합할 경우 요약 및 슬랙 전송
            print(f"✨ 적합: {judgment.get('reason')}")
            
            gpt_summary_prompt = f"아래 내용을 요약해줘: {truncated_text}"
            summary_res = client_openai.chat.completions.create(
                model="gpt-4o-mini",
                response_format={ "type": "json_object" },
                messages=[{"role": "system", "content": "You are a helpful assistant. Output JSON with 'key_points' and 'recommendations'."},
                          {"role": "user", "content": gpt_summary_prompt}]
            )
            gpt_res = json.loads(summary_res.choices[0].message.content)
            
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": "🚀 ANTIEGG 큐레이션"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*<{target_url}|{project_title}>*"}},
                {"type": "divider"},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"📌 *핵심 요약*\n" + "\n".join([f"• {p}" for p in gpt_res.get('key_points', [])])}}
            ]
            
            slack_resp = requests.post(webhook_url, json={"blocks": blocks})

            if slack_resp.status_code == 200:
                print("✅ 슬랙 전송 성공!")
                sheet.update_cell(update_row_index, status_col_idx, 'published')
                sheet.update_cell(update_row_index, publish_col_idx, 'DONE')
                break # 전송 성공 시 루프 종료
            else:
                print(f"❌ 슬랙 전송 실패 (HTTP {slack_resp.status_code})")

        except Exception as e:
            print(f"❌ {update_row_index}행 처리 중 오류 발생: {e}")
            continue

except Exception as e:
    print(f"❌ 치명적 오류: {e}")
finally:
    print("\n--- [Mix Sender] 프로세스 종료 ---")
