import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import random
import time
import re

# =========================================================
# 1. 설정 및 인증
# =========================================================
try:
    print("--- [Recruit Sender] 전체 자동화 프로세스를 시작합니다 ---")
    
    if 'GOOGLE_CREDENTIALS' not in os.environ:
        raise Exception("환경변수 GOOGLE_CREDENTIALS가 설정되지 않았습니다.")

    creds_dict = json.loads(os.environ['GOOGLE_CREDENTIALS'])
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    spreadsheet = client.open('플린트스토닝 소재 DB')
    
    TARGET_GID = 639559541
    sheet = next((s for s in spreadsheet.worksheets() if s.id == TARGET_GID), None)
    
    if not sheet:
        raise Exception(f"GID {TARGET_GID} 시트를 찾을 수 없습니다.")
    
    data = sheet.get_all_values()
    headers = [h.strip() for h in data[0]]
    df = pd.DataFrame(data[1:], columns=headers)

    COL_STATUS = 'status'
    COL_IDENTITY = 'identity_match'
    COL_TITLE = 'title'     
    COL_URL = 'url'         
    COL_LOCATION = 'location' 
    COL_EXPERIENCE = 'experience'
    COL_COMPANY = 'company'

    # 'archived' 상태인 모든 행 추출
    target_rows = df[df[COL_STATUS].str.strip().str.lower() == 'archived']

    if target_rows.empty:
        print("ℹ️ 처리할 'archived' 상태의 공고가 없습니다.")
        exit()

    print(f"총 {len(target_rows)}건의 공고를 순차적으로 처리합니다.")

    identity_col_idx = headers.index(COL_IDENTITY) + 1
    status_col_idx = headers.index(COL_STATUS) + 1
    client_openai = OpenAI(api_key=os.environ['OPENAI_API_KEY'])
    webhook_url = os.environ['SLACK_WEBHOOK_URL']
    
    session = requests.Session()

    # =========================================================
    # 2. 메인 루프 (모든 행 순회)
    # =========================================================
    for index, row in target_rows.iterrows():
        update_row_index = int(index) + 2
        
        # 제목 정제: [] 및 내부 텍스트 제거
        original_title = row[COL_TITLE]
        cleaned_title = re.sub(r'\[.*?\]', '', original_title).strip()
        
        target_url = row[COL_URL]
        sheet_company = row.get(COL_COMPANY, "회사명 미상").strip() or "회사명 미상"
        sheet_location = row.get(COL_LOCATION, "정보 없음").strip() or "정보 없음"
        sheet_experience = row.get(COL_EXPERIENCE, "경력 무관").strip() or "경력 무관"
        
        print(f"\n🔍 {update_row_index}행 검토 중: {cleaned_title}")

        try:
            # 3. [차단 우회] 브라우저 위장 헤더
            headers_ua = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Referer': 'https://www.google.com/',
            }

            time.sleep(random.uniform(3.0, 6.0))
            
            resp = session.get(target_url, headers=headers_ua, timeout=15)
            resp.raise_for_status()
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            text_content = " ".join([p.get_text().strip() for p in soup.find_all(['p', 'h2', 'h3', 'li', 'span', 'div']) if len(p.get_text().strip()) > 10])
            truncated_text = text_content[:3500]

            # 4. [적합성 판단]
            identity_prompt = f"""
            당신은 에디터 공동체 'ANTIEGG'의 전문 큐레이터입니다. 아래 채용 공고를 분석하여 에디팅 직무인지 판단하세요.

            [적합 조건]
            - 주요 업무가 글쓰기, 기획, 편집, 뉴스레터 제작, 스토리텔링인 경우
            - '에디터', '콘텐츠 기획자', '카피라이터'와 같이 텍스트 중심의 포지션인 경우

            [부적합 조건 (FALSE)]
            - 영상 편집, 디자인, 개발 위주의 공고
            - 텍스트 작업이 부차적인 단순 마케팅 퍼포먼스 공고
            - 사이드 프로젝트(채용이 아닌 경우)

            [내용] {truncated_text}
            """
            
            check_res = client_openai.chat.completions.create(
                model="gpt-4o-mini",
                response_format={ "type": "json_object" },
                messages=[
                    {"role": "system", "content": "You are a job analyst. Respond only in json format with key 'is_appropriate' (boolean)."},
                    {"role": "user", "content": identity_prompt}
                ]
            )
            is_appropriate = json.loads(check_res.choices[0].message.content).get('is_appropriate', False)
            
            # identity_match 컬럼 업데이트
            sheet.update_cell(update_row_index, identity_col_idx, str(is_appropriate).upper())

            # [수정 포인트] 적합성 판단 결과가 FALSE인 경우
            if not is_appropriate:
                print(f"⚠️ 부적합 공고 판단: status를 'dropped'로 변경합니다.")
                sheet.update_cell(update_row_index, status_col_idx, 'dropped') # status 변경
                continue

            # 5. [요약 생성] 3개 불릿 포인트 제한 프롬프트
            summary_prompt = f"""
            동료 에디터들을 위해 채용 공고를 json 포맷으로 정리하세요. 

            [지침]:
            1. roles, requirements, preferences, recommendations 키를 사용하세요.
            2. **중요**: 각 항목은 반드시 **최대 3개의 불릿**으로만 구성하세요.
            3. **문구 유지**: roles, requirements, preferences에서 원문의 표현을 최대한 그대로 사용하세요.
            4. **경력 삭제**: requirements에서 "N년 경력" 등 모든 숫자 형태의 경력 요건은 삭제하세요.
            5. 'recommendations'는 "~한 분"으로 끝맺음하세요.

            [내용] {truncated_text}
            """
            
            summary_res = client_openai.chat.completions.create(
                model="gpt-4o-mini",
                response_format={ "type": "json_object" },
                messages=[
                    {"role": "system", "content": "You are a professional editor. Respond only in json format with keys: 'roles', 'requirements', 'preferences', 'recommendations' (all lists)."},
                    {"role": "user", "content": summary_prompt}
                ]
            )
            gpt_res = json.loads(summary_res.choices[0].message.content)
            
            # 6. 슬랙 전송
            display_title = f"[{sheet_company}] {cleaned_title}"
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": "*오늘 올라온 채용 공고*"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*{display_title}*"}},
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*지역*\n{sheet_location}"},
                        {"type": "mrkdwn", "text": f"*경력*\n{sheet_experience}"}
                    ]
                },
                {"type": "divider"},
                {"type": "section", "text": {"type": "mrkdwn", "text": "📌 *주요 역할*\n" + "\n".join([f"• {r}" for r in gpt_res.get('roles', [])])}},
                {"type": "section", "text": {"type": "mrkdwn", "text": "📌 *요구 역량*\n" + "\n".join([f"• {req}" for req in gpt_res.get('requirements', [])])}},
                {"type": "section", "text": {"type": "mrkdwn", "text": "📌 *우대 사항*\n" + "\n".join([f"• {p}" for p in gpt_res.get('preferences', [])])}},
                {"type": "section", "text": {"type": "mrkdwn", "text": "📌 *이런 분께 추천해요*\n" + "\n".join([f"• {rec}" for rec in gpt_res.get('recommendations', [])])}},
                {"type": "divider"},
                {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "상세 공고 보러가기", "emoji": True}, "style": "primary", "url": target_url}]}
            ]
            
            resp_slack = requests.post(webhook_url, json={"blocks": blocks})
            
            if resp_slack.status_code == 200:
                sheet.update_cell(update_row_index, status_col_idx, 'published')
                print(f"✅ 전송 성공: {display_title}")
            else:
                print(f"❌ 슬랙 전송 실패 (상태 코드: {resp_slack.status_code})")

            time.sleep(2)

        except Exception as e:
            print(f"❌ {update_row_index}행 처리 중 오류: {e}")
            continue

    print("--- 모든 대기 중인 공고 처리가 완료되었습니다 ---")

except Exception as e:
    print(f"❌ 치명적 오류: {e}")
