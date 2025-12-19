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
    "name": "오퍼센트",
    "url": "https://offercent.co.kr/company-list?jobCategories=0040002%2C0170004",
    "gid": "639559541" # 오퍼센트 탭
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

# [전용] 데이터 수집 - 최종 보정판
def scrape_projects():
    driver = get_driver()
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")
    urls_check = set()
    
    try:
        driver.get(CONFIG["url"])
        # 타임아웃 에러 방지: 요소 하나만 나타나도 즉시 실행
        wait = WebDriverWait(driver, 15)
        try:
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "a")))
        except:
            print("⚠️ 로딩 지연 발생 - 계속 진행합니다.")

        # 누락 방지를 위한 충분한 스크롤 (10회)
        for i in range(10):
            # 현재 페이지에 존재하는 모든 카드(a 태그) 획득
            cards = driver.find_elements(By.TAG_NAME, "a")
            
            for card in cards:
                href = card.get_attribute("href")
                # 상세 공고 페이지(/job/) 링크인지 확인
                if not href or "/job/" not in href: continue
                
                try:
                    # 카드 내부의 모든 텍스트(span) 추출
                    all_spans = card.find_elements(By.CSS_SELECTOR, "span.greet-typography")
                    
                    company = ""
                    title_list = []
                    
                    for s in all_spans:
                        cls = s.get_attribute("class") or ""
                        txt = s.text.strip()
                        if not txt or "채용 중인 공고" in txt: continue
                        
                        # 제목 클래스(xlyipyv)가 있으면 제목 리스트에 추가
                        if "xlyipyv" in cls:
                            title_list.append(txt)
                        # 제목이 아니고 아직 회사명이 비어있다면 회사명으로 저장
                        elif not company:
                            company = txt

                    # 한 카드 내의 여러 제목 처리
                    for title in title_list:
                        unique_id = f"{href}_{title}"
                        if unique_id not in urls_check:
                            new_data.append({
                                'company': company,
                                'title': title,
                                'url': href,
                                'scraped_at': today
                            })
                            urls_check.add(unique_id)
                except:
                    continue
            
            # 스크롤 후 새로운 콘텐츠가 로드될 시간을 줌 (비엠스마일 누락 방지)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3) 

    finally: 
        driver.quit()
    
    print(f"✅ 총 {len(new_data)}건의 공고를 수집했습니다.")
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
