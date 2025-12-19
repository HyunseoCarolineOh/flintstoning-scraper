import os, time, json, re
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# [설정] 이 파일 전용 정보
CONFIG = {
    "name": "Mix.day",
    "url": "https://mix.day/",
    "gid": "981623942" # Mix 탭
}

# [공통] 시트 연결 (GID로 찾기)
def get_worksheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(os.environ['GOOGLE_CREDENTIALS'])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1nKPVCZ6zAOfpqCjV6WfjkzCI55FA9r2yvi9XL3iIneo/edit")
    # 순서가 바뀌어도 ID로 탭을 찾음
    sheet = next((s for s in spreadsheet.worksheets() if str(s.id) == CONFIG["gid"]), None)
    if not sheet: raise Exception(f"{CONFIG['gid']} 시트를 못 찾았습니다.")
    return sheet

# [공통] 브라우저 실행
def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"})
    return driver

# [전용] 데이터 수집
def scrape_projects():
    driver = get_driver()
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        driver.get(CONFIG["url"])
        # 카드 요소가 로드될 때까지 대기
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "article")))

        # Mix.day는 무한 스크롤이 있을 수 있으므로 약간의 스크롤 수행
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        
        # 1. 각 콘텐츠 카드(article) 추출
        articles = driver.find_elements(By.CSS_SELECTOR, "article")
        
        for art in articles:
            try:
                # 2. 제목 추출: 'line-clamp-2' 클래스를 포함한 span 태그가 제목임
                title_elem = art.find_element(By.CSS_SELECTOR, "span.line-clamp-2")
                title = title_elem.text.strip()
                
                # 3. 링크 추출: Mix.day는 카드 전체 클릭 방식인 경우가 많음
                # 만약 article 자체가 링크가 아니라면 내부의 hidden link나 특정 요소를 찾아야 함
                # 현재 구조에서는 클릭 시 이동하는 URL을 잡기 위해 상위 a 태그나 script 경로 확인 필요
                # 일단 href가 포함된 가장 가까운 a 태그를 찾음
                try:
                    url = art.find_element(By.XPATH, "./ancestor::a").get_attribute("href")
                except:
                    # article 내부에 a 태그가 따로 있는 경우
                    url = art.find_element(By.CSS_SELECTOR, "a").get_attribute("href")

                if title and url and "http" in url:
                    if not any(d['url'] == url for d in new_data):
                        new_data.append({'title': title, 'url': url, 'scraped_at': today})
            except Exception as e:
                continue
                
    finally: driver.quit()
    return new_data
# [공통] 스마트 저장 (헤더 이름 기준)
def update_sheet(ws, data):
    if not data: return print(f"[{CONFIG['name']}] 새 공고 없음")
    all_v = ws.get_all_values()
    headers = all_v[0] if all_v else ['title', 'url', 'scraped_at', 'status', 'location']
    col_map = {name: i for i, name in enumerate(headers)}
    existing_urls = {row[col_map['url']] for row in all_v[1:] if len(row) > col_map['url']}
    
    rows = []
    for item in data:
        if item['url'] in existing_urls: continue
        row = [''] * len(headers)
        for k, v in item.items():
            if k in col_map: row[col_map[k]] = v
        if 'status' in col_map: row[col_map['status']] = 'archived'
        rows.append(row)
    
    if rows: ws.append_rows(rows); print(f"💾 {CONFIG['name']} {len(rows)}건 저장")

if __name__ == "__main__":
    ws = get_worksheet(); data = scrape_projects(); update_sheet(ws, data)
