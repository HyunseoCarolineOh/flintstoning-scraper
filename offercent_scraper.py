import os, time, json, re, traceback
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# [설정] 이 파일 전용 정보
CONFIG = {
    "name": "오퍼센트",
    "url": "https://offercent.co.kr/company-list?jobCategories=0040002%2C0170004",
    "gid": "639559541"
}

# [공통] 시트 연결 로직
def get_worksheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(os.environ['GOOGLE_CREDENTIALS'])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1nKPVCZ6zAOfpqCjV6WfjkzCI55FA9r2yvi9XL3iIneo/edit")
    sheet = next((s for s in spreadsheet.worksheets() if str(s.id) == CONFIG["gid"]), None)
    if not sheet: raise Exception(f"{CONFIG['gid']} 시트를 못 찾았습니다.")
    return sheet

# [공통] 브라우저 실행 설정 (차단 방지 옵션 포함)
def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu") 
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_argument("--disable-blink-features=AutomationControlled")
    
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver

# [전용] 오퍼센트 맞춤 데이터 수집 로직
def scrape_projects():
    driver = get_driver()
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")
    urls_check = set()
    
    try:
        print(f"🌐 {CONFIG['url']} 접속 시도 중...")
        driver.get(CONFIG["url"])
        time.sleep(5)

        # [핵심 수정] 타임아웃 발생 시에도 강제 진행하도록 예외 처리
        wait = WebDriverWait(driver, 20)
        print("🔍 공고 리스트 탐색 시작...")
        try:
            wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'job')]")))
        except TimeoutException:
            print("⚠️ 타임아웃 발생! 하지만 데이터 추출을 강제 진행합니다.")

        # [핵심 수정] 리스트 활성화를 위한 초기 스크롤
        driver.execute_script("window.scrollTo(0, 500);")
        time.sleep(3)

        for scroll_idx in range(10):
            # [전용] XPATH를 이용한 정밀 타겟팅
            job_cards = driver.find_elements(By.XPATH, "//a[contains(@href, 'job')]")
            print(f"✅ 스크롤 {scroll_idx + 1}회차: {len(job_cards)}개의 공고 후보 발견")

            for card in job_cards:
                try:
                    if not card.is_displayed(): continue
                    href = card.get_attribute("href")
                    if not href: continue

                    # [전용] 카드 내 텍스트 추출 로직
                    content_els = card.find_elements(By.TAG_NAME, "span")
                    texts = [el.text.strip() for el in content_els if el.text.strip()]
                    
                    if len(texts) >= 2:
                        company_name = texts[0]
                        job_title = texts[1]
                        
                        # 필터링: 날짜 정보 제외
                        if any(x in job_title for x in ["전", "개월", "일", "주"]) or len(job_title) < 2:
                            continue
                            
                        data_id = f"{href}_{job_title}"
                        if data_id not in urls_check:
                            new_data.append({
                                'company': company_name,
                                'title': job_title,
                                'url': href,
                                'scraped_at': today
                            })
                            urls_check.add(data_id)
                except:
                    continue
            
            # 다음 데이터 로딩을 위한 하단 스크롤
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)

    except Exception:
        print("❌ 수집 중 상세 오류 발생:")
        print(traceback.format_exc())
    finally: 
        driver.quit()
    
    return new_data

# [공통] 구글 시트 업데이트 로직
def update_sheet(ws, data):
    if not data: 
        print(f"[{CONFIG['name']}] 새로 수집된 공고가 없습니다.")
        return

    all_v = ws.get_all_values()
    headers = all_v[0] if all_v else ['company', 'title', 'url', 'scraped_at', 'status']
    col_map = {name: i for i, name in enumerate(headers)}
    
    url_idx = col_map.get('url', 2)
    existing_urls = {row[url_idx] for row in all_v[1:] if len(row) > url_idx}
    
    rows_to_append = []
    for item in data:
        if item['url'] in existing_urls: continue
        
        row = [''] * len(headers)
        for k, v in item.items():
            if k in col_map: row[col_map[k]] = v
        
        if 'status' in col_map: row[col_map['status']] = 'archived'
        rows_to_append.append(row)
    
    if rows_to_append:
        ws.append_rows(rows_to_append)
        print(f"💾 {CONFIG['name']} 신규 공고 {len(rows_to_append)}건 저장 완료")
    else:
        print(f"[{CONFIG['name']}] 시트에 이미 모두 반영되어 있습니다.")

# [메인 실행부]
if __name__ == "__main__":
    try:
        ws = get_worksheet()
        data = scrape_projects()
        update_sheet(ws, data)
    except Exception:
        print("❌ 실행 중 최종 오류 발생:")
        print(traceback.format_exc())
