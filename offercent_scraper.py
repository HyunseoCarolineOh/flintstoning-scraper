def get_projects():
    driver = get_driver()
    new_data = []
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        print("🌐 오퍼센트 접속 중...")
        driver.get(SCRAPE_URL)
        
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(5) 

        # 스크롤 다운
        for i in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        
        elements = driver.find_elements(By.TAG_NAME, "a")
        print(f"🔍 탐색된 링크 수: {len(elements)}개")

        # [수정] 무시할 키워드 리스트 (여기에 포함된 줄은 데이터로 쓰지 않음)
        IGNORE_KEYWORDS = ["채용 중인 공고", "채용마감", "마감임박", "상시채용", "D-", "NEW"]

        for elem in elements:
            try:
                full_url = elem.get_attribute("href")
                if not full_url or full_url == SCRAPE_URL: continue
                
                raw_text = elem.text.strip()
                if not raw_text: continue

                lines = raw_text.split('\n')
                
                # [핵심 수정] 의미 있는 텍스트만 남기기 (필터링)
                cleaned_lines = []
                for line in lines:
                    text = line.strip()
                    if not text: continue
                    
                    # "채용 중인 공고" 같은 상태 메시지가 있으면 건너뜀
                    is_ignored = False
                    for keyword in IGNORE_KEYWORDS:
                        if keyword in text:
                            is_ignored = True
                            break
                    
                    if not is_ignored:
                        cleaned_lines.append(text)
                
                # 필터링 후에도 데이터가 2줄 이상이어야 함 (회사명 + 제목)
                if len(cleaned_lines) < 2: continue

                # 이제 0번째가 회사명, 1번째가 진짜 제목일 확률이 매우 높음
                company = cleaned_lines[0]
                title = cleaned_lines[1]

                # 제목이 너무 짧으면(3글자 이하) 그 다음 줄을 제목으로 시도
                if len(title) <= 3 and len(cleaned_lines) >= 3:
                    title = cleaned_lines[2]

                if len(title) > 2 and len(company) > 1:
                    if not any(d['url'] == full_url for d in new_data):
                        new_data.append({
                            'title': title,
                            'company': company,
                            'url': full_url,
                            'scraped_at': today
                        })
            except Exception:
                continue
                
    except Exception as e:
        print(f"❌ 크롤링 에러: {e}")
    finally:
        driver.quit()
            
    print(f"🎯 수집된 공고: {len(new_data)}개")
    
    # [디버깅] 실제 수집된 데이터 샘플 확인
    if len(new_data) > 0:
        print("📊 [샘플 데이터 확인]")
        for i in range(min(3, len(new_data))):
            print(f"   제목: {new_data[i]['title']} | 회사: {new_data[i]['company']}")

    return new_data
