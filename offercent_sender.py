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
# 1. 설정 및 인증 [Common: 공통 환경 설정]
# =========================================================
def main():
    try:
        print("--- [Offercent Sender] 시작 ---")
        
        # [Common] API 키 및 환경변수 로드 (보안을 위해 환경변수 사용)
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

        # [Common] 구글 스프레드시트 접근 및 데이터 로드
        spreadsheet = client.open('플린트스토닝 소재 DB') 
        sheet = spreadsheet.get_worksheet(3) # 네 번째 탭
        data = sheet.get_all_values()
        
        if not data:
            print("데이터가 없습니다.")
            return

        headers = data.pop(0)
        df = pd.DataFrame(data, columns=headers)

        # =========================================================
        # 2. 필터링 로직 [Common: 발송 대상 선별]
        # =========================================================
        # F열(상태)이 'archived'이고 publish 열이 'TRUE'인 행만 추출
        if len(df.columns) <= 5:
            print("열 개수가 부족합니다. (F열 필요)")
            return

        col_status_name = df.columns[5] 
        condition = (df[col_status_name].str.strip() == 'archived') & (df['publish'].str.strip() == 'TRUE')
        target_rows = df[condition]

        if target_rows.empty:
            print("발송할 대상(archived & publish=TRUE)이 없습니다.")
            return

        # 가장 위에 있는 한 개의 행만 처리
        row = target_rows.iloc[0]
        update_row_index = row.name + 2 
        
        # [Common] 기본 데이터 변수 할당
        project_title = row['title']
        target_url = row['url']
        company_name = row.get('company', 'Company')

        # =========================================================
        # 3. 웹 스크래핑 [Offercent Specific: 사이트 구조 맞춤 추출]
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

        # [Offercent Specific] 오퍼센트의 본문 영역(main, article 등)을 타겟팅
        content_area = soup.find('main') or soup.find('article') or soup.find('div', {'class': 'description'})
        if not content_area:
            content_area = soup

        # [Common] 텍스트 정제: 불필요한 태그 제거 및 공백 통합
        for tag in content_area(['script', 'style', 'nav', 'footer', 'iframe']):
            tag.extract()

        full_text = content_area.get_text(separator="\n", strip=True)
        cleaned_text = re.sub(r'\n+', '\n', full_text) # [Common] 토큰 절약을 위해 연속 줄바꿈 제거
        truncated_text = cleaned_text[:6000] 

        # =========================================================
        # 4. GPT 브랜드 적합성 판단 및 요약 [Common: AI 큐레이션]
        # =========================================================
        print("--- GPT 브랜드 적합성 판단 및 분석 요청 ---")
        client_openai = OpenAI(api_key=os.environ['OPENAI_API_KEY'])

        # [Common] 제외 조건 및 브랜드 가이드라인 설정
        exclude_positions = "인플루언서 마케팅, 퍼포먼스 마케팅, 그로스 해킹/그로스 마케팅 관련 모든 포지션"

        gpt_prompt = f"""
        너는 스타트업 채용 정보를 우리 브랜드 가이드에 맞춰 선별하는 전문 에디터야.

        [필터링 규칙]
        - 다음 직군에 해당하면 반드시 'is_suitable': false로 처리해: {exclude_positions}
        - 위 직군이 아니고, 일반적인 기획, 개발, 디자인, 전략 등 브랜드에 적합한 직군이면 true로 처리해.

        [지시 사항]
        아래 [채용 공고 본문]을 읽고 JSON 포맷으로 응답해줘.
        1. **is_suitable**: 적합 여부 (true/false)
        2. **reason**: 적합/부적합 판단 이유 (한 문장)
        3. **required_exp**: 경력 요건 (예: 3년 이상, 무관 등)
        4. **summary**: (적합할 경우만) '해요'체로 작성한 매력적인 2~3문장 요약.

        [채용 공고 본문]
        {truncated_text}
        """

        try:
            completion = client_openai.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "JSON 형식으로만 응답하며, 제외 직군 여부를 엄격히 판단하세요."},
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

        except Exception as e:
            print(f"⚠️ GPT 처리 오류: {e}")
            return

        # =========================================================
        # 5. 분기 처리 및 결과 발송 [Common: 조건별 사후 처리]
        # =========================================================
        
        # [Case 1] 브랜드 부적합 포지션일 경우
        if not is_suitable:
            print(f"⏩ [제외 대상] {reason}")
            sheet.update_cell(update_row_index, 6, 'excluded') # 시트 상태를 'excluded'로 변경
            return

        # [Case 2] 적합한 포지션일 경우 슬랙 전송
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
            sheet.update_cell(update_row_index, 6, 'published') # 시트 상태를 'published'로 변경
            print("✅ 상태 변경 완료 (archived -> published)")
        else:
            print(f"❌ 슬랙 전송 실패: {slack_res.status_code}")

    except Exception as e:
        print(f"\n❌ 시스템 에러 발생: {e}")

if __name__ == "__main__":
    main()
