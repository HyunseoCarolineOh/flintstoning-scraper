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
    COL_IDENTITY = 'identity_match'
    COL_TITLE = 'title'
    COL_URL = 'url'

    # status가 'archived'인 행만 필터링
    target_rows = df[df[COL_STATUS].str.strip().str.lower() == 'archived']

    if target_rows.empty:
        print("ℹ️ 'archived' 상태의 아티클이 없습니다.")
        exit()

    identity_col_idx = headers.index(COL_IDENTITY) + 1
    status_col_idx = headers.index(COL_STATUS) + 1
    client_openai = OpenAI(api_key=os.environ['OPENAI_API_KEY'])
    webhook_url = os.environ['SLACK_WEBHOOK_URL']

    # =========================================================
    # 2. 메인 루프: 적합한 아티클을 찾을 때까지 반복
    # =========================================================
    for index, row in target_rows.iterrows():
        update_row_index = int(index) + 2
        project_title = row[COL_TITLE]
        target_url = row[COL_URL]
        
        print(f"\n🔍 검토 중 ({update_row_index}행): {project_title}")

        try:
            # 3. 웹 스크래핑
            headers_ua = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(target_url, headers=headers_ua, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            paragraphs = soup.find_all(['p', 'h2', 'h3'])
            text_content = " ".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 20])
            truncated_text = text_content[:3500]

            # 4. ANTIEGG 정체성 판단
            # 필수: 연대/커뮤니티 가치 | 선택: 에디터 영감 OR 비즈니스/문화예술 연결
            identity_prompt = f"""
            너는 프리랜서 에디터 공동체 'ANTIEGG'의 편집장이야. 아래 기준에 따라 부합 여부를 판단해줘.

            [판단 기준]
            1. 필수 조건: '연대와 커뮤니티의 가치'가 있는가? (광장에서 함께 나누고 토론할 만한 주제)
            2. 선택 조건 (둘 중 하나는 반드시 충족):
               - 에디터에게 영감을 주는가? (글쓰기, 생존, 성장 인사이트)
               - 비즈니스와 문화예술의 연결고리가 있는가? (담론 형성 및 생태계 기여)

            [글 내용]
            {truncated_text}

            출력 포맷(JSON): {{"is_appropriate": true/false, "reason": "설명"}}
            """
            check_res = client_openai.chat.completions.create(
                model="gpt-4o-mini",
                response_format={ "type": "json_object" },
                messages=[{"role": "system", "content": "You are the editor-in-chief of ANTIEGG."},
                          {"role": "user", "content": identity_prompt}]
            )
            judgment = json.loads(check_res.choices[0].message.content)
            is_appropriate = judgment.get("is_appropriate", False)
            
            # [상태 관리] identity_match 업데이트 (TRUE/FALSE)
            sheet.update_cell(update_row_index, identity_col_idx, str(is_appropriate).upper())

            if not is_appropriate:
                print(f"⚠️ 부적합: {judgment.get('reason')}")
                continue

            # 5. 슬랙 메시지 생성 (인사이트 중심, 추천 대상 어미 수정)
            print(f"✨ 적합 판정: 메시지 생성을 시작합니다.")
            
            summary_prompt = f"""
            너는 ANTIEGG의 인사이트 큐레이터야. 지적이고 세련된 어투로 아래 글을 요약해줘.

            1. key_points: 본문의 핵심 맥락을 짚어주는 4개 문장.
            2. recommendations: 이 글이 필요한 구체적인 대상을 3가지 제안. 
               - 추천 대상 끝맺음: "~하신 분", "~를 찾으시는 분", "~가 고민이신 분"
               - 주의: 기업 담당자를 위한 리소스 효율화 관련 내용은 제외할 것.

            [글 내용]
            {truncated_text}

            출력 포맷(JSON): {{"key_points": [], "recommendations": []}}
            """
            
            summary_res = client_openai.chat.completions.create(
                model="gpt-4o-mini",
                response_format={ "type": "json_object" },
                messages=[{"role": "system", "content": "You are a professional insight curator. Use intellectual Korean."},
                          {"role": "user", "content": summary_prompt}]
            )
            gpt_res = json.loads(summary_res.choices[0].message.content)
            
            # 슬랙 블록 구성 (이미지 레이아웃 재현)
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": "지금 주목해야 할 아티클", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*{project_title}*"}},
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "📌 *이 글에서 이야기하는 것들*\n" + "\n".join([f"• {p}" for p in gpt_res.get('key_points', [])])}
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "📌 *이런 분께 추천해요*\n" + "\n".join([f"• {p}" for p in gpt_res.get('recommendations', [])])}
                },
                {"type": "divider"},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "아티클 보러가기", "emoji": True},
                            "style": "primary",
                            "url": target_url
                        }
                    ]
                }
            ]
            
            slack_resp = requests.post(webhook_url, json={"blocks": blocks})

            # 6. 전송 결과에 따른 status 업데이트
            if slack_resp.status_code == 200:
                print("✅ 슬랙 전송 성공!")
                # [상태 관리] 성공 시 published
                sheet.update_cell(update_row_index, status_col_idx, 'published')
                break 
            else:
                print(f"❌ 슬랙 전송 실패: {slack_resp.status_code}")
                # [상태 관리] 실패 시 failed
                sheet.update_cell(update_row_index, status_col_idx, 'failed')
                break

        except Exception as e:
            print(f"❌ {update_row_index}행 처리 오류: {e}")
            sheet.update_cell(update_row_index, status_col_idx, 'failed')
            continue

except Exception as e:
    print(f"❌ 치명적 오류: {e}")
finally:
    print("--- [Mix Sender] 프로세스 종료 ---")
