import os, time, json, re
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ==========================================
# [전용] 설정 정보
# ==========================================
CONFIG = {
    "name": "오퍼센트_통합_크롤러",
    "url": "https://offercent.co.kr/list?jobCategories=0040002%2C0170004&sort=recent",
    "gid": "639559541"
}

# ==========================================
# [공통] 구글 스프레드시트 연결 로직
# ==========================================
def get_worksheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(os.environ['GOOGLE_CREDENTIALS'])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1nKPVCZ6zAOfpqCjV6WfjkzCI55FA9r2yvi9XL3iIneo/edit")
    sheet = next((s for s in spreadsheet.worksheets() if str(s.id) == CONFIG["gid"]), None)
    if not sheet: raise Exception(f"{CONFIG['gid']} 시트를 못 찾았습니다.")
    return sheet

# ==========================================
# [공통] 셀레니움 브라우저 설정 로직
# ==========================================
def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver

# ==========================================
# [전용] 오퍼센트 사이트 데이터 수집 로직 (스크롤 강화 버전)
# ==========================================
def scrape_projects():
    driver = get_driver()
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")
    urls_check = set()
    
    try:
        print(f"🔗 접속 중: {CONFIG['url']}")
        driver.get(CONFIG["url"])
        wait = WebDriverWait(driver, 20)
        
        # [전용 선택자] 제목 클래스 xqzk367가 나타날 때까지 대기
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.xqzk367")))
        
        # ------------------------------------------------------
        # 무한 스크롤 로직: 더 이상 새로운 공고가 없을 때까지 내림
        # ------------------------------------------------------
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_count = 0
        max_scrolls = 15  # 수집량에 따라 이 숫자를 늘리세요.
        
        print("📥 모든 공고를 불러오기 위해 스크롤을 시작합니다...")
        while scroll_count < max_scrolls:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)  # 로딩 대기 (사이트 속도에 따라 2~4초 조절)
            
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                print("🏁 더 이상 불러올 공고가 없습니다.")
                break
            last_height = new_height
            scroll_count += 1
            print(f"🔄 스크롤 중... ({scroll_count}/{max_scrolls})")

        # 스크롤 완료 후 전체 카드 리스트 확보
        cards = driver.find_elements(By.CSS_SELECTOR, "a.xqzk367[href*='/jd/']")
        print(f"🔍 총 발견된 공고 카드 개수: {len(cards)}개")

        for card in cards:
            try:
                title = card.text.strip()
                full_href = card.get_attribute("href")
                clean_url = full_href.split('?')[0] # URL 파라미터 정제
                
                # [유연한 탐색] a태그의 부모 요소를 타고 올라가며 정보 탐색
                container = card.find_element(By.XPATH, "..") 
                
                company_name = "회사명 미상"
                location = ""
                experience = ""

                # 상위로 5단계까지만 올라가며 회사명(body-02)과 정보(body-03)가 있는지 확인
                for _ in range(5):
                    try:
                        # 1. 회사명 찾기 (body-02)
                        company_el = container.find_element(By.CSS_SELECTOR, 'span[data-variant="body-02"]')
                        company_name = company_el.text.strip()
                        
                        # 2. 지역/경력 찾기 (body-03)
                        info_el = container.find_element(By.CSS_SELECTOR, 'span[data-variant="body-03"]')
                        info_text = info_el.text.strip()
                        
                        if "·" in info_text:
                            parts = info_text.split("·")
                            location, experience = parts[0].strip(), parts[1].strip()
                        else:
                            location = info_text
                        
                        if company_name != "회사명 미상" and location:
                            break
                    except:
                        container = container.find_element(By.XPATH, "..")

                # 중복 데이터 수집 방지
                data_id = f"{clean_url}_{title}"
                if data_id not in urls_check:
                    new_data.append({
                        'company': company_name,
                        'title': title,
                        'location': location,
                        'experience': experience,
                        'url': clean_url,
                        'scraped_at': today
                    })
                    urls_check.add(data_id)
                    # 상세 로그는 너무 많을 수 있으니 생략하거나 필요시 주석 해제
                    # print(f"✅ 추출: {company_name} | {title}")

            except Exception:
                continue

    finally: 
        driver.quit()
    
    print(f"📦 최종 수집 완료된 공고: {len(new_data)}건")
    return new_data
# ==========================================
# [공통] 시트 데이터 업데이트 로직
# ==========================================
def update_sheet(ws, data):
    if not data: 
        print(f"[{CONFIG['name']}] 새로 수집된 공고가 없습니다.")
        return

    all_v = ws.get_all_values()
    headers = all_v[0] if all_v else ['company', 'title', 'location', 'experience', 'url', 'scraped_at', 'status']
    
    col_map = {name: i for i, name in enumerate(headers)}
    # 기존 데이터 중복 비교 (URL 파라미터 제외)
    existing_urls = {row[col_map['url']].split('?')[0] for row in all_v[1:] if len(row) > col_map['url']}
    
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

# ==========================================
# [공통] 실행 메인 루틴
# ==========================================
if __name__ == "__main__":
    try:
        ws = get_worksheet()
        data = scrape_projects()
        update_sheet(ws, data)
    except Exception as e:
        print(f"❌ 실행 중 오류 발생: {e}")
