import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

# 1. 구글 시트 인증 및 연결
# credentials.json 파일이 같은 폴더에 있어야 합니다.
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
client = gspread.authorize(creds)

# 2. 스프레드시트 열기
# '구글_스프레드시트_제목'을 실제 시트의 제목으로 바꿔주세요.
spreadsheet = client.open('플린트스토닝 소재 DB')
sheet = spreadsheet.sheet1  # 첫 번째 시트 선택

# 3. 데이터를 가져와서 DataFrame으로 변환
data = sheet.get_all_values()
# 첫 번째 행을 헤더로 설정
headers = data.pop(0)
df = pd.DataFrame(data, columns=headers)

# 4. F열의 이름(헤더) 찾기 (6번째 열 = 인덱스 5)
col_f = df.columns[5]

# 5. 조건 필터링
# 구글 시트에서 가져온 데이터는 모두 문자열일 수 있으므로 'TRUE' 문자열로 비교합니다.
condition = (df[col_f] == 'archived') & (df['publish'] == 'TRUE')

# 6. 결과 추출 (1개)
result = df[condition].head(1)

print(result)
