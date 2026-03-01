# 포트폴리오 추천기 MVP (Python + Streamlit + CLI)

기존 계산기의 한계(산수 불일치, 금융소득 종합과세 리스크, 계좌 제도 한도, IRP 위험자산 한도 경고)를 반영한 간단한 MVP입니다.

## 주요 기능
- 입력값
  - `total_capital`, `target_net_monthly_cf`, `buffer_months`
  - 토글: `avoid_fin_income_comprehensive`, `use_highdiv_separate_tax`, `include_overseas_assets`
  - 가정값 수정:
    - `yield_cash`, `yield_bond`, `yield_growth_dividend`, `yield_highdiv_dividend`
    - `withholding_tax_rate`, `fin_income_threshold`, `stt_rate_domestic`
    - `extra_tax_rate_on_excess_fin_income`
    - `overseas_capgain_tax_rate`, `overseas_basic_deduction`
- 출력값
  - 3개 카드: `안정형/월급형/성장형`
  - 인컴/성장 비중, 자산 배분(원), 세전/세후 월/연 현금흐름
  - 목표 부족분 충당을 위한 필요한 매도금액/거래세
  - 경고: 금융소득 2,000만원 초과 가능, IRP 위험자산 70% 초과 가능 등
- JSON 내보내기
  - Streamlit 다운로드/파일 저장
  - CLI `--output-json` 저장

## 계산 모델(단순화)
1. 일반 금융소득 세후:
   - `net = gross * (1 - withholding_tax_rate) - extra_tax_on_excess`
   - `extra_tax_on_excess = max(0, ordinary_fin_income - fin_income_threshold) * extra_tax_rate_on_excess_fin_income`
2. 고배당 분리과세(옵션):
   - 14/20/25/30 누진구간 단순모델 적용
3. 부족분 매도:
   - `gross_sell = shortfall / (1 - stt_rate_domestic)`
   - `stt_cost = gross_sell * stt_rate_domestic`
4. 계좌 배분:
   - MVP에서는 기존잔고 입력 없이 비중 가이드와 연간 신규 납입 가이드만 제공
   - IRP 위험자산 70% 초과 여부 경고만 구현

## 프로젝트 구조
```text
engine/
  models.py
  validators.py
  tax.py
  portfolio.py
app/
  ui.py
  cli.py
tests/
  test_engine.py
```

## 설치
```bash
cd /home/kimbb/cashflow-calculator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 실행
### 1) 웹 UI (Streamlit)
```bash
streamlit run app/ui.py
```

### 2) CLI
```bash
python3 -m app.cli \
  --total-capital 2000000000 \
  --target-net-monthly-cf 5000000 \
  --buffer-months 12 \
  --avoid-fin-income-comprehensive \
  --use-highdiv-separate-tax \
  --include-overseas-assets \
  --output-json outputs/recommendation.json
```

### 3) CLI (입력 JSON 파일 기반)
```bash
python3 -m app.cli \
  --input-json examples/input.sample.json \
  --output-json outputs/recommendation_from_json.json
```

### 4) 간편 실행 스크립트
```bash
./scripts/run_cli_from_json.sh
# 또는
./scripts/run_cli_from_json.sh examples/input.sample.json outputs/my_result.json
```

## 테스트 (TC1~TC4)
```bash
python3 -m pytest -q
```

- TC1: 인컴 중심형 산수 검증 (15.1억/80%/4.7%)
- TC2: 월 500만원 목표 달성 필요 총자산 검증 (약 16억)
- TC3: 균형/성장형 산수 검증
- TC4: 초과분 추가세금 + 부족분 매도 공식 검증

## 참고
- 세법/상품 규정은 변경될 수 있으므로 실제 투자 적용 전 최신 법령/약관 확인이 필요합니다.
- 본 MVP는 시뮬레이션 목적의 단순모델입니다.
