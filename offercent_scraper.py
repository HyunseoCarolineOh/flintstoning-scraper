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
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")
    urls_check = set()
    
    try:
        driver.get(CONFIG["url"])
        wait = WebDriverWait(driver, 25)
        # 공고 링크(제목)가 나타날 때까지 대기
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/jd/']")))
        time.sleep(5)

        # 공고 아이템들을 감싸고 있는 상위 컨테이너를 찾거나, 개별 공고 섹션을 식별합니다.
        # 오퍼센트 리스트는 보통 각 공고가 특정 단위(article 또는 div)로 묶여 있습니다.
        for _ in range(8): # 필요에 따라 스크롤 횟수 조절
            # 공고 제목 링크를 기준으로 각 공고 단위를 찾습니다.
            job_elements = driver.find_elements(By.CSS_SELECTOR, "div.x78zum5.xdt5ytf.x1iyjqo2") # 일반적인 카드 컨테이너 클래스 (상황에 따라 조정 가능)
            
            # 만약 위 선택자가 안 잡힐 경우를 대비해, 제목(a태그)의 부모 요소를 탐색하는 방식으로 접근
            cards = driver.find_elements(By.CSS_SELECTOR, "a[href*='/jd/']")

            for card in cards:
                try:
                    # 1. 제목 및 URL 추출
                    title = card.text.strip()
                    href = card.get_attribute("href")
                    
                    # 2. 공고 카드의 부모 요소로부터 회사명과 지역/경력 정보 추출
                    # 보통 a태그 주변의 div들에서 정보를 찾습니다.
                    parent_container = card.find_element(By.XPATH, "./ancestor::div[contains(@class, 'x1n2onr6')][1]") 
                    
                    # 회사명 추출 (data-variant="body-02")
                    company_el = parent_container.find_element(By.CSS_SELECTOR, 'span[data-variant="body-02"]')
                    company_name = company_el.text.strip()
                    
                    # 지역 및 경력 추출 (data-variant="body-03")
                    info_el = parent_container.find_element(By.CSS_SELECTOR, 'span[data-variant="body-03"]')
                    info_text = info_el.text.strip() # 예: "서울특별시 양천구 · 경력 무관"
                    
                    location = ""
                    experience = ""
                    if "·" in info_text:
                        parts = info_text.split("·")
                        location = parts[0].strip()
                        experience = parts[1].strip()
                    else:
                        location = info_text
                    
                    # 중복 체크 및 저장
                    data_id = f"{href}_{title}"
                    if data_id not in urls_check:
                        new_data.append({
                            'company': company_name,
                            'title': title,
                            'location': location,
                            'experience': experience,
                            'url': href,
                            'scraped_at': today
                        })
                        urls_check.add(data_id)
                except:
                    continue
            
            # 스크롤 내리기
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)

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
