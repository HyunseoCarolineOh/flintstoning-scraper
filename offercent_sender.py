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
def main():
    try:
        print("--- [Offercent Sender] 시작 ---")
        
        # 환경 변수에서 설정값 로드
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
        
        # 네 번째 탭 선택 (Index 3)
        sheet = spreadsheet.get_worksheet(3)

        # 데이터 가져오기
        data = sheet.get_all_values()
        if not data:
            print("데이터가 없습니다.")
            return

        headers = data.pop(0)
        df = pd.DataFrame(data, columns=headers)

        # =========================================================
        # 2. 필터링 (F열: archived, publish: TRUE)
        # =========================================================
        # 안전을 위해 컬럼 인덱스 대신 이름을 확인할 수도 있으나, 
        # 기존 로직(5번 인덱스=F열)을 유지하되 예외처리를 강화합니다.
        if len(df.columns) <= 5:
            print("열 개수가 부족합니다. (F열 필요)")
            return

        col_status_name = df.columns[5] # F열 (보통 'status' 또는 'archive')
        
        # 공백 제거 및 조건 확인
        condition = (df[col_status_name].str.strip() == 'archived') & (df['publish'].str.strip() == 'TRUE')
        target_rows = df[condition]

        if target_rows.empty:
            print("발송할 대상(archived & publish=TRUE)이 없습니다.")
            return

        # 첫 번째 행 선택
        row = target_rows.iloc[0]
        update_row_index = row.name + 2 # 헤더(1) + 0-based index 보정(1)
        
        print(f"▶ 선택된 행 번호: {update_row_index}")

        # =========================================================
        # 3. 데이터 추출
        # =========================================================
        
        # 시트 헤더 이름 설정 (실제 시트 헤더와 일치해야 함)
        title_col_name = 'title' 
        url_col_name = 'url'
        company_col_name = 'company' 
        # 만약 '포지션' 칼럼이 따로 있다면 여기에 추가 (현재는 title로 대체)

        missing_cols = [c for c in [title_col_name, url_col_name] if c not in row]
        if missing_cols:
            print(f"오류: 엑셀 헤더 이름({', '.join(missing_cols)})을 확인해주세요.")
            return

        project_title = row[title_col_name]
        target_url = row[url_col_name]
        
        # 회사명 처리
        if company_col_name in row and row[company_col_name]:
            company_name = row[company_col_name]
        else:
            print(f"⚠️ 경고: 회사명이 없어 'Company'로 대체합니다.")
            company_name = "Company"

        print(f"▶ [Offercent] 회사명: {company_name}")
        print(f"▶ [Offercent] 제목: {project_title}")
        print(f"▶ URL: {target_url}")

        # =========================================================
        # 4. 웹 스크래핑 (Offercent 맞춤)
        # =========================================================
        print("--- 스크래핑 시작 ---")
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

        # 본문 영역 타겟팅 (Offercent 구조 고려)
        content_area = soup.find('main') or soup.find('article') or soup.find('div', {'class': 'description'})
        
        if not content_area:
            print("⚠️ 특정 본문 영역을 찾지 못해 전체 페이지에서 텍스트를 추출합니다.")
            content_area = soup

        # 불필요한 태그 제거
        for tag in content_area(['script', 'style', 'nav', 'footer', 'iframe']):
            tag.extract()

        # 텍스트 추출
        full_text = content_area.get_text(separator="\n", strip=True)
        truncated_text = full_text[:6000] # GPT 입력 한도 고려

        if len(truncated_text) < 50:
            print("⚠️ 수집된 텍스트가 너무 적습니다. (JavaScript 로딩 페이지일 가능성 있음)")
            # 필요 시 여기서 Selenium 로직으로 분기 가능

        # =========================================================
        # 5. GPT 분석 (연차 추출 + 요약)
        # =========================================================
        print("--- GPT 분석 요청 ---")
        client_openai = OpenAI(api_key=os.environ['OPENAI_API_KEY'])

        gpt_prompt = f"""
        [역할]
        너는 스타트업 채용 정보를 분석하여 핵심 정보를 추출하고, 매력적인 소개글을 작성하는 에디터야.

        [지시 사항]
        아래 [채용 공고 본문]을 읽고 다음 정보를 JSON 포맷으로 추출해줘.

        1. **required_exp**: 지원 자격에 명시된 '경력/연차' 요건을 짧게 추출. (예: "신입", "3년 이상", "5~7년", "무관" 등)
        2. **summary**: 이 포지션의 주요 업무와 회사의 매력을 구직자에게 어필하듯 부드러운 '해요'체로 2~3문장 요약.

        [출력 예시 - JSON]
        {{
            "required_exp": "3년 이상",
            "summary": "글로벌 핀테크 서비스의 서버 개발을 담당해요. 자율적인 근무 환경과 최신 기술 스택을 경험할 수 있는 기회입니다."
        }}

        [채용 공고 본문]
        {truncated_text}
        """

        try:
            completion = client_openai.chat.completions.create(
                model="gpt-4o",  # JSON 모드 사용을 위해 gpt-4o 또는 gpt-4-turbo 권장
                messages=[
                    {"role": "system", "content": "JSON 형식으로만 응답하세요."},
                    {"role": "user", "content": gpt_prompt}
                ],
                response_format={"type": "json_object"}, 
                temperature=0.3,
            )
            
            gpt_response = completion.choices[0].message.content
            gpt_data = json.loads(gpt_response)

            extracted_exp = gpt_data.get('required_exp', '공고 본문 확인')
            extracted_summary = gpt_data.get('summary', '요약을 생성하지 못했습니다.')

        except Exception as e:
            print(f"⚠️ GPT 처리 중 오류 발생: {e}")
            extracted_exp = "확인 필요"
            extracted_summary = "요약 생성 실패 (본문 내용을 확인해주세요)"

        print("--- GPT 응답 완료 ---")

        # =========================================================
        # 6. 슬랙 전송 & 시트 업데이트
        # =========================================================
        
        # 메시지 조립
        # 포맷: <오늘 올라온 채용 공고> -> 공고명 -> 기업명 -> 포지션명 -> 연차 -> 요약 -> URL(링크변환)
        
        slack_message = f"*<오늘 올라온 채용 공고>*\n\n"
        slack_message += f"*{project_title}*\n\n"
        slack_message += f"*기업명:* {company_name}\n"
        slack_message += f"*연차:* {extracted_exp}\n\n"
        slack_message += f"*요약*\n{extracted_summary}\n\n"
        slack_message += f":링크:<{target_url}|공고 바로가기>"

        print("--- 최종 메시지 미리보기 ---")
        print(slack_message)

        print("--- 슬랙 전송 시작 ---")
        webhook_url = os.environ['SLACK_WEBHOOK_URL']
        
        payload = {"text": slack_message}
        slack_res = requests.post(webhook_url, json=payload)

        if slack_res.status_code == 200:
            print("✅ 슬랙 전송 성공!")
            
            try:
                # 상태 업데이트 (F열 = 6번째 열)
                print(f"▶ 시트 업데이트 중... (행: {update_row_index}, 열: 6)")
                sheet.update_cell(update_row_index, 6, 'published')
                print("✅ 상태 변경 완료 (archived -> published)")
            except Exception as e:
                print(f"⚠️ 시트 업데이트 실패: {e}")
        else:
            print(f"❌ 전송 실패 (Code: {slack_res.status_code})")
            print(slack_res.text)

    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")

if __name__ == "__main__":
    main()
