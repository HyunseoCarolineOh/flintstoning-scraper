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
    print("--- [Wanted Sender] 시작 ---")
    
    json_creds = os.environ['GOOGLE_CREDENTIALS']
    creds_dict = json.loads(json_creds)
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    # 시트 제목
    spreadsheet = client.open('플린트스토닝 소재 DB') 
    
    # 네 번째 탭 선택 (Index 3)
    sheet = spreadsheet.get_worksheet(3)

    # 데이터 가져오기
    data = sheet.get_all_values()
    if not data:
        print("데이터가 없습니다.")
        exit()

    headers = data.pop(0)
    df = pd.DataFrame(data, columns=headers)

    # =========================================================
    # 2. 필터링 (F열: archived, publish: TRUE)
    # =========================================================
    if len(df.columns) <= 5:
        print("열 개수가 부족합니다.")
        exit()

    col_f = df.columns[5] # F열
    
    # 조건 확인
    condition = (df[col_f].str.strip() == 'archived') & (df['publish'].str.strip() == 'TRUE')
    target_rows = df[condition]

    if target_rows.empty:
        print("발송할 대상(archived & publish=TRUE)이 없습니다.")
        exit()

    # 첫 번째 행 선택
    row = target_rows.iloc[0]
    update_row_index = row.name + 2
    
    print(f"▶ 선택된 행 번호: {update_row_index}")

    # =========================================================
    # 3. 데이터 추출 (제목, URL) - 회사명은 GPT가 찾음
    # =========================================================
    
    title_col_name = 'title' 
    url_col_name = 'url'

    if title_col_name not in row or url_col_name not in row:
        print(f"오류: 엑셀 헤더 이름('{title_col_name}', '{url_col_name}')을 확인해주세요.")
        exit()

    project_title = row[title_col_name]
    target_url = row[url_col_name]
    
    print(f"▶ 제목: {project_title}")
    print(f"▶ URL: {target_url}")

    # =========================================================
    # 4. 웹 스크래핑
    # =========================================================
    print("--- 스크래핑 시작 ---")
    headers_ua = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    response = requests.get(target_url, headers=headers_ua, timeout=10)
    if response.status_code != 200:
        print(f"접속 실패 (상태 코드: {response.status_code})")
        exit()

    soup = BeautifulSoup(response.text, 'html.parser')
    paragraphs = soup.find_all('p')
    full_text = " ".join([p.get_text() for p in paragraphs])
    truncated_text = full_text[:3000]

    # =========================================================
    # 5. GPT 요약 (회사명 추출 + 내용 요약)
    # =========================================================
    print("--- GPT 요약 요청 ---")
    client_openai = OpenAI(api_key=os.environ['OPENAI_API_KEY'])

    gpt_prompt = f"""
    너는 채용 정보를 분석하는 AI야. 아래 [채용 정보]를 보고 회사명과 요약을 추출해.
    
    [중요 지침]
    1. **회사 이름 찾기 규칙**:
       - 가장 중요한 힌트는 **제목(Title)**에 있어.
       - 제목에 `[회사명]` 혹은 `[팀명]` 처럼 대괄호가 있다면 그 안의 단어를 회사명으로 추출해.
       - 예시: "[인턴] [노트폴리오] 마케팅 담당자" -> Company: 노트폴리오
       - 만약 제목에 회사명이 없다면 본문에서 찾아.
       
    2. **함정 피하기**:
       - 본문에 "(주)원티드랩은 서울 송파구에..." 같은 문구는 채용 플랫폼의 설명일 뿐이야. **이것을 회사명으로 적지 마.** (단, 제목 자체가 원티드랩 채용인 경우는 제외)

    3. **출력 양식**:
       Company: (회사명)
       (여기서부터 요약 내용 작성)

    [채용 정보]
    제목: {project_title}
    본문: {truncated_text}
    """

    # (이후 호출 코드는 동일)
    completion = client_openai.chat.completions.create(
        model="gpt-3.5-turbo", # 또는 gpt-4o-mini 추천 (더 똑똑하고 저렴함)
        messages=[
            {"role": "system", "content": "You are a helpful HR assistant."},
            {"role": "user", "content": gpt_prompt}
        ]
    )

    full_response = completion.choices[0].message.content
    
    # [핵심] 첫 줄(회사명)과 나머지(본문) 분리하기
    lines = full_response.strip().split('\n')
    
    # 첫 줄에서 회사명 추출 ('Company:' 제거)
    first_line = lines[0]
    if first_line.startswith("Company:"):
        company_name = first_line.replace("Company:", "").strip()
        # 나머지 줄들을 다시 합쳐서 본문으로 만듦
        gpt_body = "\n".join(lines[1:]).strip()
    else:
        # 만약 GPT가 형식을 안 지켰을 경우 대비
        company_name = "채용"
        gpt_body = full_response

    print(f"▶ GPT가 찾은 회사명: {company_name}")

    # 메시지 조립
    final_message = f"*[{company_name}] 채용 공고*\n<{target_url}|{project_title}>\n\n{gpt_body}"
    
    print("--- 최종 결과물 ---")
    print(final_message)

    # =========================================================
    # 6. 슬랙 전송 & 시트 업데이트 (published 처리)
    # =========================================================
    print("--- 슬랙 전송 시작 ---")
    
    webhook_url = os.environ['SLACK_WEBHOOK_URL']
    payload = {"text": final_message}
    
    slack_res = requests.post(webhook_url, json=payload)
    
    if slack_res.status_code == 200:
        print("✅ 슬랙 전송 성공!")
        
        try:
            print(f"▶ 시트 상태 업데이트 중... (행: {update_row_index}, 열: 6)")
            sheet.update_cell(update_row_index, 6, 'published')
            print("✅ 상태 변경 완료 (archived -> published)")
        except Exception as e:
            print(f"⚠️ 상태 업데이트 실패: {e}")
            
    else:
        print(f"❌ 전송 실패 (상태 코드: {slack_res.status_code})")
        print(slack_res.text)

except Exception as e:
    print(f"\n❌ 에러 발생: {e}")
