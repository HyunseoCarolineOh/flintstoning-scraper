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

        for i in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        
        elements = driver.find_elements(By.TAG_NAME, "a")
        print(f"🔍 발견된 전체 링크 수: {len(elements)}개")

        # 무시할 키워드 (정확히 일치하거나 포함되면 해당 줄만 제외)
        # "채용 중인 공고"는 배지 텍스트이므로 제외
        IGNORE_EXACT_MATCH = ["채용 중인 공고", "채용마감", "마감임박", "상시채용", "NEW"]

        for elem in elements:
            try:
                full_url = elem.get_attribute("href")
                if not full_url or full_url == SCRAPE_URL: continue
                
                raw_text = elem.text.strip()
                if not raw_text: continue

                lines = raw_text.split('\n')
                cleaned_lines = []
                
                # 한 줄씩 검사
                for line in lines:
                    text = line.strip()
                    if not text: continue
                    
                    # 배지/상태 텍스트 제거 로직
                    should_skip = False
                    for kw in IGNORE_EXACT_MATCH:
                        if kw in text:  # 키워드가 포함되어 있으면 건너뜀
                            should_skip = True
                            break
                    # 날짜 형식(D-숫자) 제거
                    if text.startswith("D-") and len(text) < 6:
                        should_skip = True

                    if not should_skip:
                        cleaned_lines.append(text)

                # 데이터가 너무 적으면(회사명만 있거나 등) 스킵
                if len(cleaned_lines) < 2:
                    continue

                # 순서 추정: 보통 [회사명, 제목] 순서
                company = cleaned_lines[0]
                title = cleaned_lines[1]

                # 만약 첫째 줄이 카테고리(예: "마케팅") 같고 셋째 줄이 있다면 조정
                # (오퍼센트는 회사명이 먼저 나오는 경우가 많으므로 기본은 0:회사, 1:제목)
                
                # 제목 유효성 체크 (너무 짧으면 다음 줄 확인)
                if len(title) < 2 and len(cleaned_lines) > 2:
                    title = cleaned_lines[2]

                # 최종 저장 조건
                if len(title) > 1 and len(company) > 0:
                    # 중복 체크 (현재 수집 목록 내에서)
                    if not any(d['url'] == full_url for d in new_data):
                        # [디버깅] 무엇을 수집했는지 출력
                        print(f"  ✅ 수집함: [{company}] {title}")
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
            
    print(f"🎯 최종 수집된 공고: {len(new_data)}개")
    return new_data
