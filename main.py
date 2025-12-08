import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

# 1. 환경변수에서 시크릿 가져오기 (파일을 읽는 게 아니라, 깃허브 금고를 엽니다)
# 주의: 깃허브 Secret 이름을 'GOOGLE_CREDENTIALS'로 저장했는지 꼭 확인하세요!
json_creds = os.environ['GOOGLE_CREDENTIALS']
creds_dict = json.loads(json_creds)

# 2. 인증 설정 (파일 경로 대신 딕셔너리 사용)
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

# [중요] from_json_keyfile_name -> from_json_keyfile_dict 로 변경됨
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# 3. 스프레드시트 열기
# '구글_스프레드시트_제목'을 본인의 실제 시트 제목으로 바꿔주세요.
spreadsheet = client.open('플린트스토닝 소재 DB')
sheet = spreadsheet.sheet1

# 4. 데이터 가져오기
data = sheet.get_all_values()
if not data:
    print("데이터가 없습니다.")
else:
    headers = data.pop(0)
    df = pd.DataFrame(data, columns=headers)

    # 5. 필터링 (F열 & publish=TRUE)
    # F열이 존재하는지 확인
    if len(df.columns) > 5:
        col_f = df.columns[5]
        
        # 조건: F열이 archived 이고, publish가 TRUE
        condition = (df[col_f] == 'archived') & (df['publish'] == 'TRUE')
        result = df[condition].head(1)

        print("--- 추출 결과 ---")
        print(result)
    else:
        print("열의 개수가 부족합니다 (F열 없음)")
