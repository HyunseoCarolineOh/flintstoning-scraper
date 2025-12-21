import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import re

# =========================================================
# 1. 설정 및 인증 [Common]
# =========================================================
def main():
    try:
        print("--- [Offercent Sender] 시작 ---")
        
        # 환경변수 로드
        if 'GOOGLE_CREDENTIALS' not in os.environ:
            raise ValueError("GOOGLE_CREDENTIALS 환경 변수가 설정되지 않았습니다.")
        if 'OPENAI_API_KEY' not in os.environ:
            raise ValueError("OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")
        if 'SLACK_WEBHOOK_URL' not in os.environ:
            raise ValueError("SLACK_WEBHOOK_URL 환경 변수가 설정되지 않았습니다.")

        json_creds = os.environ['GOOGLE_CREDENTIALS']
        creds_dict = json.loads(json_creds)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

        # 시트 열기
        spreadsheet = client.open('플린트스토닝 소재 DB') 
        sheet = spreadsheet.get_worksheet(3) 
        data = sheet.get_all_values()
        
        if not data:
            print("데이터가 없습니다.")
            return

        headers = data.pop(0)
        df = pd.DataFrame(data, columns=headers)

        # =========================================================
        # 2. 필터링 로직 [Common: 발송 대상 선별]
        # =========================================================
        # [변경점] 'publish' 조건 제거: F열(상태)이 'archived'인 행만 추출
        if len(df.columns) <= 5:
            print("열 개수가 부족합니다. (F열 필요)")
            return

        col_status_name = df.columns[5] 
        condition = (df[col_status_name].str.strip() == 'archived')
        target_rows = df[condition]

        if target_rows.empty:
            print("발송할 대상(archived)이 없습니다.")
            return

        # 가장 상단 행 선택
        row = target_rows.iloc[0]
        update_row_index = row.name + 2 
        
        project_title = row['title']
        target_url = row['url']
        company_name = row.get('company', 'Company')

        # =========================================================
        # 3. 웹 스크래핑 [Offercent Specific]
        # =========================================================
        print(f"--- [Offercent] 스크래핑 시작: {target_url} ---")
        headers_ua = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        try:
            response = requests.get(target_url, headers=headers_ua, timeout=15)
            response.raise_for_status()
        except Exception as e:
            print(f"❌ 접속 실패: {e}")
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        content_area = soup.find('main') or soup.find('article') or soup.find('div', {'class': 'description'})
        if not content_area: content_area = soup

        for tag in content_area(['script', 'style', 'nav', 'footer', 'iframe']):
            tag.extract()

        full_text = content_area.get_text(separator="\n", strip=True)
        cleaned_text = re.sub(r'\n+', '\n', full_text) 
        truncated_text = cleaned_text[:6000] 

        # =========================================================
        # 4. GPT 브랜드 적합성 판단 [Common]
        # =========================================================
        print("--- GPT 브랜드 적합성 판단 및 분석 요청 ---")
        client_openai = OpenAI(api_key=os.environ['OPENAI_API_KEY'])

        # 제외 조건 명시
        exclude_positions = "인플루언서 마케팅, 퍼포먼스 마케팅, 그로스 해킹/그로스 마케팅 관련 모든 포지션"

        gpt_prompt = f"""
        너는 스타트업 채용 정보를 선별하는 전문 에디터야.

        [필터링 규칙]
        - 다음 직군에 해당하면 반드시 'is_suitable': false로 처리해: {exclude_positions}
        - 위 직군이 아니고, 기획, 개발, 디자인, 브랜딩 등 브랜드에 적합한 직군이면 true로 처리해.

        [지시 사항]
        아래 [채용 공고 본문]을 읽고 JSON으로 응답해줘.
        1. **is_suitable**: 적합 여부 (true/false)
        2. **reason**: 판단 이유
        3. **required_exp**: 경력 요건
        4. **summary**: (적합 시) '해요'체 요약 (2~3문장).

        [채용 공고 본문]
        {truncated_text}
        """

        completion = client_openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "JSON 형식으로만 응답하며 제외 직군을 엄격히 필터링하세요."},
                {"role": "user", "content": gpt_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        
        gpt_data = json.loads(completion.choices[0].message.content)
        is_suitable = gpt_data.get('is_suitable', False)
        reason = gpt_data.get('reason', '판단 근거 없음')
        extracted_exp = gpt_data.get('required_exp', '본문 확인')
        extracted_summary = gpt_data.get('summary', '')

        # =========================================================
        # 5. 분기 처리 및 결과 발송 [Common]
        # =========================================================
        
        if not is_suitable:
            print(f"⏩ [제외 대상] {reason}")
            sheet.update_cell(update_row_index, 6, 'excluded') # 제외 표시
            return

        # 적합한 경우 슬랙 전송
        slack_message = (
            f"*<오늘 올라온 채용 공고>*\n\n"
            f"*{project_title}*\n\n"
            f"*기업명:* {company_name}\n"
            f"*연차:* {extracted_exp}\n\n"
            f"*요약*\n{extracted_summary}\n\n"
            f"🔗 <{target_url}|공고 바로가기>"
        )

        print("--- 슬랙 전송 시작 ---")
        webhook_url = os.environ['SLACK_WEBHOOK_URL']
        slack_res = requests.post(webhook_url, json={"text": slack_message})

        if slack_res.status_code == 200:
            print("✅ 슬랙 전송 성공!")
            sheet.update_cell(update_row_index, 6, 'published') # 발송 완료 표시
        else:
            print(f"❌ 슬랙 전송 실패: {slack_res.status_code}")

    except Exception as e:
        print(f"\n❌ 에러: {e}")

if __name__ == "__main__":
    main()
