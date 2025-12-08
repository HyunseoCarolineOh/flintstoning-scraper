import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

# 1. 인증 설정 (같은 폴더에 있는 credentials.json을 찾음)
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
client = gspread.authorize(creds)

# 2. 스프레드시트 열기
# 주의: 구글 시트 제목을 정확히 적어주세요
spreadsheet = client.open('구글_스프레드시트_제목') 
sheet = spreadsheet.sheet1

# 3. 데이터 가져오기
data = sheet.get_all_values()
headers = data.pop(0)
df = pd.DataFrame(data, columns=headers)

# 4. 필터링 (F열 & publish=TRUE)
# F열 이름 자동 찾기 (6번째 열)
col_f = df.columns[5]

# 조건: F열이 archived 이고, publish가 TRUE
condition = (df[col_f] == 'archived') & (df['publish'] == 'TRUE')
result = df[condition].head(1)

print(result)
