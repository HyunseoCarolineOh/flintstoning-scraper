import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import time
import random
import re

# =========================================================
# 1. 설정 및 인증
# =========================================================
try:
    print("--- [Surfit Sender] 전체 자동화 프로세스를 시작합니다 ---")
    
    if 'GOOGLE_CREDENTIALS' not in os.environ:
        raise Exception("환경변수 GOOGLE_CREDENTIALS가 설정되지 않았습니다.")

    creds_dict = json.loads(os.environ['GOOGLE_CREDENTIALS'])
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    spreadsheet = client.open('플린트스토닝 소재 DB')
    
    # [GID 2112710663 기반 워크시트 선택]
    TARGET_GID = 2112710663
    sheet = next((s for s in spreadsheet.worksheets() if s.id == TARGET_GID), None)
    
    if not sheet:
        raise Exception(f"GID가 {TARGET_GID}인 워크시트를 찾을 수 없습니다.")
    
    data = sheet.get_all_values()
    headers = [h.strip() for h in data[0]]
    df = pd.DataFrame(data[1:], columns=headers)

    COL_STATUS = 'status'
    COL_IDENTITY = 'identity_match'
    COL_TITLE = 'title'
    COL_URL = 'url'

    # 'archived' 상태인 모든 행 추출
    target_rows = df[df[COL_STATUS].str.strip().str.lower() == 'archived']

    if target_rows.empty:
        print("ℹ️ 처리할 'archived' 상태의 아티클이 현재 시트에 없습니다.")
        exit()

    print(f"총 {len(target_rows)}건의 아티클 처리를 시작합니다.")

    identity_col_idx = headers.index(COL_IDENTITY) + 1
    status_col_idx = headers.index(COL_STATUS) + 1
    client_openai = OpenAI(api_key=os.environ['OPENAI_API_KEY'])
    webhook_url = os.environ['SLACK_WEBHOOK_URL']
    
    session = requests.Session()

    # =========================================================
    # 2. 메인 루프: 모든 'archived' 행을 끝까지 순회합니다.
    # =========================================================
    for index, row in target_rows.iterrows():
        update_row_index = int(index) + 2
        project_title = row[COL_TITLE]
        target_url = row[COL_URL]
        
        print(f"\n🔍 {update_row_index}행 검토 중: {project_title}")

        try:
            # 3. 웹 스크래핑 (차단 방지를 위한 브라우저 위장 헤더)
            headers_ua = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
                'Referer': 'https://www.google.com/'
            }
            
            # 요청 간 랜덤 대기 (차단 방지)
            time.sleep(random.uniform(3.0, 5.0))
            
            resp = session.get(target_url, headers=headers_ua, timeout=15)
            resp.raise_for_status()
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            paragraphs = soup.find_all(['p', 'h2', 'h3'])
            text_content = " ".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 20])
            truncated_text = text_content[:3500]

            # 4. ANTIEGG 정체성 판단 (JSON 응답 강화)
            identity_prompt = f"""
            안녕하세요, 당신은 프리랜서 에디터 공동체 'ANTIEGG'의 편집장입니다. 
            당신은 단순히 키워드를 찾는 것이 아니라, 글의 '깊이'와 '관점'을 보고 ANTIEGG 독자들에게 영감을 줄 수 있는지 판단합니다.
            
            [판단 원칙: "깊이 없는 정보는 거절한다"]
            에디터가 자신의 관점을 투영하여 분석하거나, 독자가 생각할 거리를 던지는 '담론' 형태의 글을 선호합니다.
            
            [사례 학습 (Few-Shot: 판단 근거 포함)]
            - ✅ 적합: '네이버와 돌고래유괴단 협업' (이유: 브랜드 간 협업의 창의적 문법을 분석함)
            - ✅ 적합: '제로클릭 시대의 마케팅' (이유: 변화하는 생태계에 대한 전략적 관점을 제시함)
            - ❌ 부적합: '무인 창업 아이템 추천' (이유: 단순 정보 나열이며 에디터의 성장과 관련 없음)
            - ❌ 부적합: '단순 앱 프로젝트 성공기' (이유: 기술적 구현 위주이며 콘텐츠적 인사이트가 부족함)
            
            [최종 지침]
            - 만약 글이 '전문 에디터'의 업무 범위를 벗어난 기술/경영 정보라면 단호하게 FALSE를 반환하세요.
            - 조금이라도 단순 홍보성 글로 느껴진다면 FALSE를 반환하세요.

            [글 내용]
            {truncated_text}
            """
            
            check_res = client_openai.chat.completions.create(
                model="gpt-4o-mini",
                response_format={ "type": "json_object" },
                messages=[
                    {"role": "system", "content": "You are a professional editor. Respond only in json format with keys: 'is_appropriate' (boolean), 'reason' (string)."},
                    {"role": "user", "content": identity_prompt}
                ]
            )
            judgment = json.loads(check_res.choices[0].message.content)
            is_appropriate = judgment.get("is_appropriate", False)
            
            # identity_match 업데이트
            time.sleep(1)
            sheet.update_cell(update_row_index, identity_col_idx, str(is_appropriate).upper())

            # [수정] 부적합 시 status를 'dropped'로 변경
            if not is_appropriate:
                print(f"⚠️ 부적합 판정: {judgment.get('reason')}")
                sheet.update_cell(update_row_index, status_col_idx, 'dropped')
                continue

            # 5. 슬랙 메시지 생성
            summary_prompt = f"""
            당신은 ANTIEGG의 인사이트 큐레이터입니다. 지적이고 세련된 어투로 아래 글을 소개해 주세요.
            어투는 매우 정중하고 지적인 경어체 (~합니다, ~해드립니다)를 사용해 주세요. 

            1. key_points: 본문의 핵심 맥락을 짚어주는 문장을 4개 내외로 작성해 주세요.
            2. recommendations: 이 글이 꼭 필요한 에디터를 3가지 내외의 유형으로 제안해 주세요. 
               - **핵심 지침**: 추천 대상은 반드시 '에디터'의 업무, 고민, 성장과 연결되어야 합니다.
               - 문구 예시: "새로운 브랜드 스토리텔링 방식을 고민하는 분", "글의 깊이를 더할 문화적 관점이 필요한 분"
               - 끝맺음: "~한 분" (예: ~하는 분, ~를 찾는 분)
               - 주의사항 : "에디터"라는 말을 직접 사용하지 말 것. 
            
            [글 내용]
            {truncated_text}
            """
            
            summary_res = client_openai.chat.completions.create(
                model="gpt-4o-mini",
                response_format={ "type": "json_object" },
                messages=[
                    {"role": "system", "content": "Respond only in json format with keys: 'key_points', 'recommendations' (lists). Use formal Korean style."},
                    {"role": "user", "content": summary_prompt}
                ]
            )
            gpt_res = json.loads(summary_res.choices[0].message.content)
            
            # 6. 슬랙 전송
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": "지금 주목해야 할 아티클", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*{project_title}*"}},
                {"type": "divider"},
                {"type": "section", "text": {"type": "mrkdwn", "text": "📌 *이 글에서 이야기하는 것들*\n" + "\n".join([f"• {p}" for p in gpt_res.get('key_points', [])])}},
                {"type": "section", "text": {"type": "mrkdwn", "text": "📌 *이런 분께 추천해요*\n" + "\n".join([f"• {p}" for p in gpt_res.get('recommendations', [])])}},
                {"type": "divider"},
                {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "아티클 보러가기", "emoji": True}, "style": "primary", "url": target_url}]}
            ]
            
            slack_resp = requests.post(webhook_url, json={"blocks": blocks})

            if slack_resp.status_code == 200:
                print("✅ 전송 성공")
                sheet.update_cell(update_row_index, status_col_idx, 'published')
            else:
                print(f"❌ 전송 실패 ({slack_resp.status_code})")
                sheet.update_cell(update_row_index, status_col_idx, 'failed')

            # [수정] break 제거하여 모든 행 처리
            time.sleep(2) 

        except Exception as e:
            print(f"❌ {update_row_index}행 처리 오류: {e}")
            if "429" in str(e):
                time.sleep(60)
            continue

except Exception as e:
    print(f"❌ 치명적 오류: {e}")
finally:
    print("--- [Surfit Sender] 모든 프로세스가 종료되었습니다 ---")
