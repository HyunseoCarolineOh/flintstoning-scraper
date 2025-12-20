import os, time, json, re
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# [설정] 오퍼센트 전용 정보
CONFIG = {
    "name": "오퍼센트",
    "url": "https://offercent.co.kr/company-list?jobCategories=0040002%2C0170004",
    "gid": "639559541"
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

# [공통] 브라우저 실행 설정 (모바일 레이아웃 대응)
def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    # 사람처럼 보이기 위한 User-Agent 설정
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver

# [전용] 데이터 수집 로직 (순서 기반 짝짓기 버전)
def scrape_projects():
    driver = get_driver()
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")
    urls_check = set()
    
    # 디버깅용 스크린샷 저장 경로
    output_dir = "screenshots"
    os.makedirs(output_dir, exist_ok=True)

    try:
        driver.get(CONFIG["url"])
        
        # 1. 공고 데이터 로딩 대기
        wait = WebDriverWait(driver, 20)
        try:
            print("⏳ 모바일 레이아웃 데이터 로딩 대기 중...")
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'span[data-variant="body-02"]')))
            time.sleep(5) 
        except:
            print("⚠️ 로딩 시간이 초과되었습니다. 현재 화면에서 수집을 시도합니다.")

        # 진단용 스크린샷 찍기
        driver.save_screenshot(os.path.join(output_dir, f"offercent_check_{today}.png"))

        # 2. 스크롤하며 데이터 수집
        for scroll_idx in range(10):
            elements = driver.find_elements(By.CSS_SELECTOR, 'span[data-variant
