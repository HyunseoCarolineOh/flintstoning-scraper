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
    print("--- [Mix Sender] 프로세스를 시작합니다 ---")
    
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

    # status가 'archived'인 행만 필터링합니다.
    target_rows = df[df[COL_STATUS].str.strip().str.lower() == 'archived']

    if target_rows.empty:
        print("ℹ️ 'archived' 상태의 아티클이 현재 시트에 없습니다.")
        exit()

    identity_col_idx = headers.index(COL_IDENTITY) + 1
    status_col_idx = headers.index(COL_STATUS) + 1
    client_openai = OpenAI(api_key=os.environ['OPENAI_API_KEY'])
    webhook_url = os.environ['SLACK_WEBHOOK_URL']

    # =========================================================
    # 2. 메인 루프: 적합한 아티클을 찾을 때까지 반복합니다.
    # =========================================================
    for index, row in target_rows.iterrows():
        update_row_index = int(index) + 2
        project_title = row[COL_TITLE]
        target_url = row[COL_URL]
        
        print(f"\n🔍 {update_row_index}행의 아티클을 검토하고 있습니다: {project_title}")

        try:
            # 3. 웹 스크래핑을 수행합니다.
            headers_ua = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(target_url, headers=headers_ua, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            paragraphs = soup.find_all(['p', 'h2', 'h3'])
            text_content = " ".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 20])
            truncated_text = text_content[:3500]

            # =========================================================
            # 4. ANTIEGG 정체성 판단 (파인튜닝된 프롬프트 적용)
            # =========================================================
            identity_prompt = f"""
            안녕하세요, 당신은 프리랜서 에디터 공동체 'ANTIEGG'의 편집장입니다. 
            아래 [글 내용]을 읽고 ANTIEGG의 정체성에 부합하는지 신중하게 판단해 주세요.
            
            [판단 기준 및 가이드라인]
            1. 필수 조건: '연대와 커뮤니티의 가치'가 담겨 있나요? (광장에서 함께 나누고 토론할 만한 담론형 주제)
            2. 선택 조건 (둘 중 하나는 반드시 충족):
               - 에디터에게 성장의 영감을 주는가? (콘텐츠 마케팅, 브랜드 전략, B2B 인사이트 등)
               - 비즈니스와 문화예술의 연결고리를 보여주는가?
            
            [학습 데이터: 적합/부적합 사례]
            - ✅ 적합: 브랜드 협업 사례, 컨셉 브랜딩, 커뮤니티 운영 회고, 마케팅 프로모션 분석, 광고 비평.
            - ❌ 부적합: 단순 기능 개선기(UX/UI), 소자본 창업 아이템 추천, 개인적인 앱 출시 성공기, 수익성 중심의 정보.
            
            [글 내용]
            {truncated_text}
            
            출력 포맷(JSON): {{"is_appropriate": true/false, "reason": "위 가이드라인에 근거하여 판단 이유를 설명해 주세요."}}
            """
            check_res = client_openai.chat.completions.create(
                model="gpt-4o-mini",
                response_format={ "type": "json_object" },
                messages=[{"role": "system", "content": "당신은 ANTIEGG의 친절하고 전문적인 편집장입니다."},
                          {"role": "user", "content": identity_prompt}]
            )
            judgment = json.loads(check_res.choices[0].message.content)
            is_appropriate = judgment.get("is_appropriate", False)
            
            # [상태 관리] identity_match 컬럼을 업데이트합니다.
            sheet.update_cell(update_row_index, identity_col_idx, str(is_appropriate).upper())

            if not is_appropriate:
                print(f"⚠️ 아쉽게도 부적합 판정을 받았습니다: {judgment.get('reason')}")
                continue

            # 5. 슬랙 메시지 생성을 시작합니다.
            print(f"✨ 적합한 아티클을 찾았습니다. 요약 메시지 생성을 시작합니다.")
            
            summary_prompt = f"""
            당신은 ANTIEGG의 인사이트 큐레이터입니다. 독자분들에게 지적이고 세련된 어투로 아래 글을 소개해 주세요.

            1. key_points: 본문의 핵심 맥락을 짚어주는 4개의 문장을 작성해 주세요.
            2. recommendations: 이 글이 꼭 필요한 대상을 3가지 제안해 주세요. 
               - 추천 대상의 끝맺음은 반드시 "~하신 분", "~를 찾으시는 분", "~가 고민이신 분"과 같은 형태로 작성해 주세요.
               - 주의 사항: 기업 담당자를 위한 리소스 효율화 관련 내용은 제외해 주세요.

            어투: 매우 정중하고 지적인 경어체를 사용해 주세요 (~합니다, ~해드립니다).

            [글 내용]
            {truncated_text}

            출력 포맷(JSON): {{"key_points": [], "recommendations": []}}
            """
            
            summary_res = client_openai.chat.completions.create(
                model="gpt-4o-mini",
                response_format={ "type": "json_object" },
                messages=[{"role": "system", "content": "당신은 지적이고 다정한 ANTIEGG의 큐레이터입니다."},
                          {"role": "user", "content": summary_prompt}]
            )
            gpt_res = json.loads(summary_res.choices[0].message.content)
            
            # 6. 슬랙으로 메시지를 전송합니다. 
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

            # 7. 최종 결과에 따라 status를 업데이트합니다.
            if slack_resp.status_code == 200:
                print("✅ 슬랙 전송에 성공하였습니다!")
                sheet.update_cell(update_row_index, status_col_idx, 'published')
                break 
            else:
                print(f"❌ 슬랙 전송에 실패하였습니다. (에러 코드: {slack_resp.status_code})")
                sheet.update_cell(update_row_index, status_col_idx, 'failed')
                break

        except Exception as e:
            print(f"❌ {update_row_index}행 처리 중 오류가 발생하였습니다: {e}")
            sheet.update_cell(update_row_index, status_col_idx, 'failed')
            continue

except Exception as e:
    print(f"❌ 치명적인 오류가 발생하여 프로세스를 종료합니다: {e}")
finally:
    print("--- [Mix Sender] 모든 프로세스가 종료되었습니다 ---")
