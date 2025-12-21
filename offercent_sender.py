import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import re

def main():
    try:
        print("--- [Offercent Sender] 시작 ---")
        
        # 1. 설정 및 인증 [Common]
        json_creds = os.environ['GOOGLE_CREDENTIALS']
        creds_dict = json.loads(json_creds)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

        # 2. 시트 연결 [Common]
        spreadsheet = client.open('플린트스토닝 소재 DB')
        TARGET_SHEET_ID = 1045981234  # 시트 GID 입력
        try:
            sheet = spreadsheet.get_worksheet_by_id(TARGET_SHEET_ID)
        except:
            sheet = spreadsheet.get_worksheet(3)

        data = sheet.get_all_values()
        headers = data.pop(0)
        df = pd.DataFrame(data, columns=headers)

        # 3. 컬럼 매핑 [Common]
        def find_col(names, columns):
            for n in names:
                if n in columns: return n
            return None

        status_col = find_col(['status', '상태'], df.columns)
        title_col = find_col(['title', '제목', '공고명'], df.columns)
        url_col = find_col(['url', 'URL', '링크'], df.columns)
        company_col = find_col(['company', '회사명'], df.columns)

        # 4. 필터링 [Common]
        condition = (df[status_col].str.strip().str.lower() == 'archived')
        target_rows = df[condition]

        if target_rows.empty:
            print("처리할 데이터가 없습니다.")
            return

        row = target_rows.iloc[0]
        update_row_index = row.name + 2
        project_title = row[title_col]
        target_url = row[url_col]
        company_name = row[company_col] if company_col else "Company"

        # 5. 스크래핑 [Offercent Specific]
        headers_ua = {'User-Agent': 'Mozilla/5.0...'}
        response = requests.get(target_url, headers=headers_ua, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')

        # [Offercent Specific] 본문 영역 추출
        content_area = soup.find('main') or soup.find('article') or soup.find('div', {'class': 'description'}) or soup
        
        # [Common] 텍스트 정제
        for tag in content_area(['script', 'style', 'nav', 'footer']): tag.extract()
        full_text = content_area.get_text(separator="\n", strip=True)
        truncated_text = re.sub(r'\n+', '\n', full_text)[:6000]

        # 6. GPT 분석 [Common]
        client_openai = OpenAI(api_key=os.environ['OPENAI_API_KEY'])
        gpt_prompt = f"인플루언서, 퍼포먼스, 그로스 직군은 제외하고 요약해줘: {truncated_text}"

        completion = client_openai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "JSON 형식 응답"}, {"role": "user", "content": gpt_prompt}],
            response_format={"type": "json_object"}
        )
        gpt_data = json.loads(completion.choices[0].message.content)

        # 7. 발송 및 업데이트 [Common]
        status_col_idx = headers.index(status_col) + 1 

        if not gpt_data.get('is_suitable'):
            sheet.update_cell(update_row_index, status_col_idx, 'excluded')
            return

        # 슬랙 전송 [Common]
        slack_msg = f"*{project_title}*\n{gpt_data.get('summary')}\n🔗 {target_url}"
        requests.post(os.environ['SLACK_WEBHOOK_URL'], json={"text": slack_msg})

        # 시트 업데이트 [Common]
        sheet.update_cell(update_row_index, status_col_idx, 'published')
        print("처리 완료")

    except Exception as e:
        print(f"에러: {e}")

if __name__ == "__main__":
    main()
