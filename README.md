# RSI 상승 다이버전스 데일리 — 완전 자동 업로드

매일 **KST 09:00 일봉 마감** 기준으로 시총 100위 코인·미국 시총 100위 주식을 스캔해서
RSI 상승 다이버전스가 **컨펌된 자산을 각 1개** 골라 **쇼츠 + 가로 영상 + 블로그 글**을 만들고,
**오전 10:00에 예약 공개**합니다. GitHub Actions(무료)에서 돌기 때문에 노트북이 꺼져 있어도 됩니다.

```
09:17  GitHub Actions 시작 (09:47 자동 재시도, 이미 발행됐으면 건너뜀)
 ├─ 코인: CoinGecko 시총 100위 → 스테이블·래핑 토큰 제외 → Binance(실패 시 OKX) UTC 일봉
 ├─ 주식: 미국 시총 100위 → Yahoo 일봉 (전일 정규장)
 ├─ 다이버전스 판정 → 자산군별 1개 선정 → 과거 동일 신호 성적표 계산
 ├─ 차트 · AI 음성(edge-tts) · 자막 → 쇼츠(1080x1920) + 가로(1920x1080) 렌더링
 └─ YouTube 2편 업로드(10:00 예약 공개) → Blogger 글(10:00 예약 발행) → 영상 설명에 블로그 링크 추가
10:00  공개
```

## 판정 기준

| 항목 | 값 |
|---|---|
| 지표 | TradingView 내장 **RSI Divergence Indicator**와 동일 로직 (RSI 14, 피벗 좌5/우5, 저점 간격 5~60봉, RSI 피벗 저점 기준 · 가격은 같은 봉의 저가 비교) |
| 추가 필터 | 첫 저점 RSI ≤ 30 |
| 컨펌 시점 | 이번 저점 이후 5번째 봉이 09:00 KST에 마감된 날 (TV에서 라벨이 뜨는 시점과 같음) |
| 여러 개면 | 시가총액이 가장 큰 종목 |
| 없으면 | ① 다이버전스는 났지만 첫 저점 RSI 30~35 → ② 컨펌까지 1~3봉 남은 후보 순으로 "근접 후보" 소개, 그것도 없으면 "신호 없음" |
| 미국 휴장일 | (KST 일·월요일, 미국 공휴일 다음 날) 주식 파트는 "휴장"으로 처리, 코인만 소개 |
| 과거 성적표 | 같은 조건 과거 신호의 5/10/20일 뒤 종가 수익률 · 상승 비율, "아무 날이나 샀을 때" 평균과 비교 |

---

## 1회 세팅 (약 30분)

### 1) GitHub 저장소 만들기
1. github.com 가입/로그인 → 오른쪽 위 **+ → New repository**
2. 이름 `rsi-divergence-daily`, **Public** 선택 → Create repository
   - Public이어야 Actions가 무제한 무료이고, 블로그 차트 이미지(jsDelivr)가 보입니다. 비밀 키는 Secrets에 암호화돼 공개되지 않습니다.
3. 새 저장소 화면의 **uploading an existing file** 클릭 → 압축 푼 폴더 **안의 내용 전부**를 끌어다 놓기 → Commit changes
   - `.github` 폴더가 빠지면: **Add file → Create new file** → 파일 이름 칸에 `.github/workflows/daily.yml` 입력 → 내용 붙여넣기 → Commit

### 2) Blogger 블로그 만들기
1. blogger.com → 유튜브와 **같은 구글 계정**으로 블로그 생성
2. 대시보드 주소창의 숫자(`blogID=1234567890…` 또는 `/blog/posts/1234567890…`)가 **블로그 ID**

### 3) Google Cloud 설정 (유튜브·블로거 API 키)
1. console.cloud.google.com → 상단 프로젝트 선택 → **새 프로젝트** (이름 아무거나)
2. **API 및 서비스 → 라이브러리**에서 `YouTube Data API v3`, `Blogger API v3` 각각 **사용 설정**
3. **Google 인증 플랫폼(Google Auth Platform) → 시작하기**: 앱 이름·지원 이메일 입력, 대상 **외부** → 만들기
4. **대상(Audience) → 앱 게시 → 프로덕션으로 푸시**
   - ⚠ "테스트" 상태로 두면 토큰이 7일 뒤 만료돼 업로드가 멈춥니다.
5. **클라이언트 → 클라이언트 만들기** → 유형 **웹 애플리케이션**
   → 승인된 리디렉션 URI에 `https://developers.google.com/oauthplayground` 추가 → 만들기
   → **클라이언트 ID**와 **클라이언트 보안 비밀번호** 복사

### 4) Refresh Token 받기 (설치 없이 웹에서)
1. https://developers.google.com/oauthplayground 접속
2. 오른쪽 위 ⚙ → **Use your own OAuth credentials** 체크 → 3-5의 ID/비밀번호 입력
3. 왼쪽 Step 1 입력칸에 아래를 붙여넣고 **Authorize APIs**
   ```
   https://www.googleapis.com/auth/youtube https://www.googleapis.com/auth/blogger
   ```
4. 유튜브 채널 계정으로 로그인 (브랜드 채널이면 그 채널 선택)
   → "Google에서 확인하지 않은 앱" 경고 → **고급 → (앱 이름)(으)로 이동** → 허용
5. Step 2 → **Exchange authorization code for tokens** → **Refresh token** 복사

### 5) GitHub에 키 등록
저장소 **Settings → Secrets and variables → Actions**

**Secrets** 탭 → New repository secret:

| 이름 | 값 |
|---|---|
| `GOOGLE_CLIENT_ID` | 3-5 클라이언트 ID |
| `GOOGLE_CLIENT_SECRET` | 3-5 클라이언트 보안 비밀번호 |
| `GOOGLE_REFRESH_TOKEN` | 4-5 Refresh token |
| `BLOGGER_BLOG_ID` | 2-2 블로그 ID |
| `COINGECKO_API_KEY` | (선택) coingecko.com 무료 Demo 키 — 요청 제한(429) 예방 |

**Variables** 탭 (선택):

| 이름 | 기본값 | 설명 |
|---|---|---|
| `CHANNEL_NAME` | RSI 다이버전스 데일리 | 영상 상단·인사말에 표시 |
| `TTS_VOICE` | ko-KR-InJoonNeural | 여성 음성: `ko-KR-SunHiNeural` |
| `YT_PRIVACY` | schedule | `schedule`(10시 예약) / `public` / `unlisted` / `private` |
| `OVERSOLD` | 30 | 첫 저점 RSI 필터 |
| `IMAGE_MODE` | jsdelivr | 저장소를 Private로 둘 때만 `inline` |

### 6) 첫 실행
1. 저장소 **Actions** 탭 → 워크플로 사용 동의 버튼 클릭
2. 왼쪽 **RSI 다이버전스 데일리 → Run workflow**
   1. `mode = check` → 로그에 ✅ 유튜브 채널명 / 블로그 이름이 나오면 키 정상
   2. `mode = preview` → 실제 시세로 영상만 생성 (업로드 X). 실행 결과 화면 맨 아래 **Artifacts**에서 mp4 다운로드해 확인
   3. 마음에 들면 끝. 다음 날부터 매일 자동 실행됩니다. (당장 올리려면 `mode = publish`)

### 7) ⚠ 유튜브 공개 업로드 잠금 해제 (중요)
구글 정책상 **심사받지 않은 API 프로젝트로 올린 영상은 '비공개'로 잠깁니다.**
- 심사 신청: https://support.google.com/youtube/contact/yt_api_form ("YouTube API Services – Audit and Quota Extension")
  — 용도: 본인 채널에 본인 콘텐츠 자동 업로드, 사용자 1명
- 승인 전까지는 매일 업로드는 정상으로 되지만 비공개 상태 → 휴대폰 **YouTube Studio 앱**에서 공개로 바꿔주세요 (영상당 10초).
- 블로그는 이 제한이 없어 10시에 자동 공개됩니다. (블로그에 넣은 영상은 비공개 동안 재생 안 됨)

---

## 문제 해결
| 증상 | 원인 / 해결 |
|---|---|
| `invalid_grant` | 토큰 만료 → 3-4 "프로덕션" 게시 확인 후 4단계 다시 |
| 영상이 비공개로만 올라감 | 7단계 심사 전 정상 동작 |
| 10시보다 늦게 공개 | GitHub 스케줄 지연(가끔 30분+). 10시 이후 완료되면 즉시 공개로 올림 |
| 음성 없이 자막만 | edge-tts·gTTS 모두 실패한 날. 로그의 `tts` 경고 확인 |
| 블로그 차트 이미지 안 보임 | 저장소가 Private → Public 전환 또는 `IMAGE_MODE=inline` |
| `git push` 권한 오류 | Settings → Actions → General → Workflow permissions → **Read and write** |
| 같은 날 영상 2개 | `state/history.json`에 기록돼 재실행 시 이어서 처리함. 수동 publish를 연달아 누르지 마세요 |

## 구조
```
.github/workflows/daily.yml   매일 09:17·09:47 KST 실행
rsi_daily/indicators.py       RSI(TV와 동일 RMA) · 피벗 · 다이버전스 · 과거 성적표
rsi_daily/data.py             CoinGecko / Binance / OKX / Yahoo 수집
rsi_daily/scan.py             자산군별 선정
rsi_daily/script.py           대본 · 제목 · 설명 · 태그
rsi_daily/charts.py           차트 (영상 애니메이션용 레이어 분리)
rsi_daily/video.py            장면 합성 · 자막 · ffmpeg 인코딩
rsi_daily/tts.py              edge-tts → gTTS → 무음 폴백
rsi_daily/blog.py             Blogger HTML
rsi_daily/publish.py          YouTube 예약 업로드 · Blogger 예약 발행
state/history.json            발행 기록 (중복 업로드 방지)
docs/posts/<날짜>/            블로그 이미지
assets/bgm.mp3                (선택) 넣으면 배경음악으로 깔림 — 저작권 없는 음원만
tests/test_indicators.py      판정 로직 테스트
```

## 로컬 실행 (선택)
```bash
pip install -r requirements.txt
python -m rsi_daily build --demo     # 합성 데이터로 영상 미리보기 → out/
python -m rsi_daily build            # 실제 시세
python tests/test_indicators.py
```

> 본 도구가 만드는 콘텐츠는 기술적 지표 자동 스캔 결과이며 투자 권유가 아닙니다.
