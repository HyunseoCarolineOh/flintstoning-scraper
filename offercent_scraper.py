import os, time, json, re
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# [설정] 오퍼센트 새로운 리스트 페이지 전용 정보
CONFIG = {
    "name": "오퍼센트_신규리스트",
    "url": "https://offercent.co.kr/list?jobCategories=0040002%2C0170004&sort=recent",
    "gid": "639559541"  # 기존 시트 GID 유지 (필요시 변경)
}

# [공통] 시트 연결
def get_worksheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(os.environ['GOOGLE_CREDENTIALS'])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1nKPVCZ6zAOfpqCjV6WfjkzCI55FA9r2yvi9XL3iIneo/edit")
    
    sheet = next((s for s in spreadsheet.worksheets() if str(s.id) == CONFIG["gid"]), None)
    if not sheet: raise Exception(f"{CONFIG['gid']} 시트를 못 찾았습니다.")
    return sheet

# [공통] 브라우저 실행 설정
def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver

# [전용] 데이터 수집 로직 (제공해주신 HTML 구조 반영)
def scrape_projects():
    driver = get_driver()
    driver.set_window_size(1920, 1080) # 실행 창 크기 명시
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")
    
    try:
        print(f"🔗 접속 중: {CONFIG['url']}")
        driver.get(CONFIG["url"])
        
        # 1. 페이지 로딩 대기 강화
        time.sleep(10) # 충분한 초기 로딩 시간 부여
        
        # 2. 공고 카드가 실제로 존재하는지 체크
        cards = driver.find_elements(By.CSS_SELECTOR, "a[href*='/jd/']")
        print(f"🔍 발견된 공고 카드 개수: {len(cards)}개")

        if len(cards) == 0:
            # 카드가 없다면 페이지 소스 일부 출력 (디버깅용)
            print("❗ 공고 카드를 찾지 못했습니다. 선택자를 확인하세요.")
            return []

        for card in cards:
            try:
                href = card.get_attribute("href")
                title = card.text.strip()
                
                # 부모 요소를 못 찾을 경우를 대비해 예외 처리 강화
                try:
                    # 제공하신 HTML 구조상 a태그 상위에 정보가 있으므로 탐색 시도
                    # 만약 아래 구문에서 에러가 나면 텍스트를 못 가져옵니다.
                    parent = card.find_element(By.XPATH, "./ancestor::div[contains(@class, 'x1n2onr6')][1]")
                    company = parent.find_element(By.CSS_SELECTOR, 'span[data-variant="body-02"]').text.strip()
                    info = parent.find_element(By.CSS_SELECTOR, 'span[data-variant="body-03"]').text.strip()
                    
                    print(f"✅ 수집 성공: {company} - {title}")
                    
                    # (이하 기존 분리 로직 동일...)
                    location = info.split('·')[0].strip() if '·' in info else info
                    experience = info.split('·')[1].strip() if '·' in info else ""
                    
                    new_data.append({
                        'company': company, 'title': title, 'location': location,
                        'experience': experience, 'url': href, 'scraped_at': today
                    })
                except Exception as inner_e:
                    print(f"⚠️ 개별 카드 분석 실패 ({title}): {inner_e}")
                    continue
            except:
                continue
    finally: 
        driver.quit()
    return new_data
    
# [공통] 시트 데이터 업데이트
def update_sheet(ws, data):
    if not data: 
        print(f"[{CONFIG['name']}] 새로 수집된 공고가 없습니다.")
        return

    all_v = ws.get_all_values()
    # 헤더에 location과 experience가 추가됨
    headers = all_v[0] if all_v else ['company', 'title', 'location', 'experience', 'url', 'scraped_at', 'status']
    
    col_map = {name: i for i, name in enumerate(headers)}
    existing_urls = {row[col_map['url']] for row in all_v[1:] if len(row) > col_map['url']}
    
    rows_to_append = []
    for item in data:
        if item['url'] in existing_urls: continue
        
        row = [''] * len(headers)
        for k, v in item.items():
            if k in col_map: row[col_map[k]] = v
        
        if 'status' in col_map: row[col_map['status']] = 'new'
        rows_to_append.append(row)
    
    if rows_to_append:
        ws.append_rows(rows_to_append)
        print(f"💾 {CONFIG['name']} 신규 공고 {len(rows_to_append)}건 저장 완료")

if __name__ == "__main__":
    try:
        ws = get_worksheet()
        data = scrape_projects()
        update_sheet(ws, data)
    except Exception as e:
        print(f"❌ 실행 중 오류 발생: {e}")
