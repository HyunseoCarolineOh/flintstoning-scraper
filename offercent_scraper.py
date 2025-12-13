def get_projects():
    driver = get_driver()
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")

    # [중복 방지용] 이미 수집한 URL을 빠르게 찾기 위해 set 사용
    collected_urls = set()

    try:
        print("🌐 오퍼센트 접속 중...")
        driver.get(SCRAPE_URL)
        
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(3) 

        # ---------------------------------------------------------
        # 내부 함수: 현재 화면에 보이는 공고들을 긁어모으는 로직
        # ---------------------------------------------------------
        def scrape_current_view():
            elements = driver.find_elements(By.TAG_NAME, "a")
            count = 0
            
            BAD_KEYWORDS = ["채용 중인 공고", "채용마감", "마감임박", "상시채용", "NEW", "D-"]

            for elem in elements:
                try:
                    full_url = elem.get_attribute("href")
                    # URL이 없거나, 자기 자신(메인)이거나, 이미 수집한 URL이면 패스
                    if not full_url or full_url == SCRAPE_URL or full_url in collected_urls: 
                        continue
                    
                    raw_text = elem.text.strip()
                    if not raw_text: continue

                    lines = raw_text.split('\n')
                    cleaned_lines = []
                    
                    for line in lines:
                        text = line.strip()
                        if not text: continue
                        
                        is_bad = False
                        for bad in BAD_KEYWORDS:
                            if bad in text:
                                is_bad = True
                                break
                        if not is_bad:
                            cleaned_lines.append(text)

                    if len(cleaned_lines) < 2: continue

                    company = cleaned_lines[0]
                    title = cleaned_lines[1]

                    if len(title) <= 3 and len(cleaned_lines) > 2:
                        title = cleaned_lines[2]

                    if len(title) > 1 and len(company) > 1:
                        new_data.append({
                            'title': title,
                            'company': company,
                            'url': full_url,
                            'scraped_at': today
                        })
                        collected_urls.add(full_url) # 수집 목록에 등록
                        count += 1
                except:
                    continue
            return count
        # ---------------------------------------------------------

        print("⬇️ 스크롤과 동시에 수집을 시작합니다...")
        
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_count = 0
        
        while True:
            # 1. [중요] 스크롤 내리기 전에 일단 현재 보이는 것들 수집! (맨 위 공고 확보)
            found = scrape_current_view()
            # print(f"   (스크롤 전/후 수집된 개수: {found}개)")
            
            # 2. 스크롤 다운
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3) # 로딩 대기
            
            # 3. 높이 비교 (더 내려갔나?)
            new_height = driver.execute_script("return document.body.scrollHeight")
            scroll_count += 1
            print(f"   ...스크롤 {scroll_count}회 진행 (누적 수집: {len(new_data)}개)")

            if new_height == last_height:
                # 혹시 마지막 로딩 후 놓친 게 있을 수 있으니 한 번 더 수집
                scrape_current_view()
                print("🏁 페이지 끝 도달")
                break
                
            last_height = new_height
                
    except Exception as e:
        print(f"❌ 크롤링 에러: {e}")
    finally:
        driver.quit()
            
    print(f"🎯 최종 수집된 공고: {len(new_data)}개")
    
    if len(new_data) > 0:
        print("📊 [샘플 데이터]")
        for i in range(min(3, len(new_data))):
             print(f"   제목: {new_data[i]['title']} / 회사: {new_data[i]['company']}")

    return new_data
