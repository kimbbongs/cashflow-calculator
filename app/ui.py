from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from typing import Dict, Iterable, Tuple

import streamlit as st

# Ensure top-level packages (e.g., `engine`) are importable when Streamlit runs from `app/`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.models import Assumptions, PortfolioCard
from engine.portfolio import (
    format_krw,
    generate_target_portfolio_recommendations,
    result_to_json,
    save_result_json,
)


ASSET_LABELS: Dict[str, str] = {
    "reserve_cash": "버퍼 현금",
    "income_cash": "인컴-현금",
    "income_bond": "인컴-채권",
    "income_growth_dividend": "인컴-배당성장",
    "income_highdiv": "인컴-고배당",
    "growth_domestic": "성장-국내",
    "growth_overseas": "성장-해외",
}


def _render_kv_table(rows: Iterable[Tuple[str, str]]) -> None:
    st.table([{"항목": key, "값": value} for key, value in rows])


def _total_capital_from_card(card: PortfolioCard) -> float:
    return sum(card.asset_allocation.values())


def _planned_sell_net_monthly(card: PortfolioCard, assumptions: Assumptions) -> float:
    growth_domestic = card.asset_allocation.get("growth_domestic", 0.0)
    growth_overseas = card.asset_allocation.get("growth_overseas", 0.0)
    total_growth = growth_domestic + growth_overseas
    if total_growth <= 0:
        return 0.0

    planned_sell_annual = total_growth * assumptions.sustainable_growth_sell_rate
    domestic_sell = min(planned_sell_annual, growth_domestic)
    overseas_sell = max(0.0, planned_sell_annual - domestic_sell)

    domestic_net = domestic_sell * (1 - assumptions.stt_rate_domestic)
    overseas_taxable = max(0.0, overseas_sell - assumptions.overseas_basic_deduction)
    overseas_tax = overseas_taxable * assumptions.overseas_capgain_tax_rate
    overseas_net = max(0.0, overseas_sell - overseas_tax)

    return (domestic_net + overseas_net) / 12


def render_card(card: PortfolioCard, target_net_monthly_cf: float, assumptions: Assumptions) -> None:
    required_total_capital = _total_capital_from_card(card)
    monthly_delta = card.cashflow.net_monthly - target_net_monthly_cf
    planned_sell_monthly = _planned_sell_net_monthly(card, assumptions)
    planned_total_monthly = card.cashflow.net_monthly + planned_sell_monthly
    planned_delta = planned_total_monthly - target_net_monthly_cf

    st.subheader(card.name)
    st.caption(card.profile_note)

    c1, c2, c3 = st.columns(3)
    c1.metric("필요 총자산", format_krw(required_total_capital))
    c2.metric(
        "인컴 기준 세후 월 현금흐름",
        format_krw(card.cashflow.net_monthly),
        delta=f"{format_krw(abs(monthly_delta))} {'여유' if monthly_delta >= 0 else '부족'}",
    )
    c3.metric(
        "계획매도 반영 월 현금흐름",
        format_krw(planned_total_monthly),
        delta=f"{format_krw(abs(planned_delta))} {'여유' if planned_delta >= 0 else '부족'}",
    )

    st.caption(f"인컴/성장 비중: {card.income_ratio:.0%} / {card.growth_ratio:.0%}")
    st.progress(card.income_ratio)
    st.caption(f"전략: {card.growth_strategy}")

    if card.cashflow.shortfall_annual > 0:
        st.warning(
            f"목표 대비 연간 {format_krw(card.cashflow.shortfall_annual)} 부족합니다. "
            "부족분은 성장자산 매도 전략으로 보완하는 시나리오입니다."
        )
    else:
        st.success("인컴 현금흐름만으로 목표를 충족합니다.")

    with st.expander("절세계좌 배분 보기", expanded=True):
        allocation_rows = [(account, format_krw(amount)) for account, amount in card.account_allocation.items()]
        ratio_rows = [(f"{account} 비중", f"{ratio:.0%}") for account, ratio in card.account_ratio_guide.items()]
        st.markdown("**계좌별 배분 금액**")
        _render_kv_table(allocation_rows)
        st.markdown("**계좌별 비중**")
        _render_kv_table(ratio_rows)

    with st.expander("자산 배분 상세 보기", expanded=False):
        asset_rows = [
            (ASSET_LABELS.get(key, key), format_krw(amount))
            for key, amount in card.asset_allocation.items()
            if amount > 0
        ]
        _render_kv_table(asset_rows)

    with st.expander("세금/현금흐름 상세 보기", expanded=False):
        flow_rows = [
            ("세전 연 현금흐름", format_krw(card.cashflow.gross_annual)),
            ("세후 연 현금흐름", format_krw(card.cashflow.net_annual)),
            ("계획매도 반영 세후 월 현금흐름", format_krw(planned_total_monthly)),
            ("세후 월 목표", format_krw(card.cashflow.target_net_monthly)),
            ("목표 대비 연 부족분", format_krw(card.cashflow.shortfall_annual)),
            ("국내 매도 거래세 추정", format_krw(card.cashflow.stt_cost)),
        ]
        if card.cashflow.overseas_sell_required > 0:
            flow_rows.extend(
                [
                    ("해외 추가 매도 추정", format_krw(card.cashflow.overseas_sell_required)),
                    ("해외세 추정", format_krw(card.cashflow.overseas_tax_estimate)),
                ]
            )
        st.markdown("**현금흐름 상세**")
        _render_kv_table(flow_rows)

        tax_rows = [
            ("총 일반 금융소득(세전)", format_krw(card.tax.gross_ordinary_fin_income)),
            ("총 고배당 소득(세전)", format_krw(card.tax.gross_highdiv_income)),
            ("일반계좌 소득(세전)", format_krw(card.tax.general_income)),
            ("ISA 소득(세전)", format_krw(card.tax.isa_income)),
            ("연금계좌 소득(세전)", format_krw(card.tax.pension_income)),
            ("일반 원천징수세", format_krw(card.tax.withheld_tax)),
            ("종합과세 추가세", format_krw(card.tax.extra_tax_on_excess)),
            ("고배당 분리과세", format_krw(card.tax.highdiv_separate_tax)),
            ("ISA 과세", format_krw(card.tax.isa_tax)),
            ("연금계좌 과세", format_krw(card.tax.pension_tax)),
            ("총 세금", format_krw(card.tax.total_tax)),
        ]
        if card.tax.suppressed_ordinary_income > 0:
            tax_rows.append(("종합과세 회피로 제외된 소득", format_krw(card.tax.suppressed_ordinary_income)))
        st.markdown("**세금 계산 상세**")
        _render_kv_table(tax_rows)

    with st.expander("가정값/한도 보기", expanded=False):
        contribution_rows = [(k, format_krw(v)) for k, v in card.annual_contribution_guide.items()]
        _render_kv_table(contribution_rows)

    if card.cashflow.overseas_sell_required > 0:
        st.info("국내 성장자산만으로 부족분을 충당하기 어려운 경우 해외자산 매도도 포함해 계산합니다.")

    if card.warnings:
        st.markdown("**주의사항**")
        for warning in card.warnings:
            st.warning(warning)


def main() -> None:
    st.set_page_config(page_title="현금흐름 포트폴리오 추천기", layout="wide")
    st.title("현금흐름 포트폴리오 추천기")
    st.caption("원하는 세후 월현금흐름(백만원)만 입력하면 안정형/밸런스형/성장형 3가지 포트폴리오를 자동 구성합니다.")

    with st.expander("사용 방법", expanded=True):
        st.markdown(
            "1. `희망 세후 월현금흐름`을 **백만원 단위**로 입력합니다. (예: 5 = 500만원)\n"
            "2. 버퍼 개월 수를 정하면 생활비 현금을 먼저 떼어두고, 나머지로 포트폴리오를 구성합니다.\n"
            "3. 해외자산 포함, 세금 계산, 절세계좌(ISA/연금저축·IRP) 활용이 자동 반영됩니다.\n"
            "4. 결과의 `필요 총자산`은 인컴 + 성장자산 계획매도(기본 연 4%)를 합쳐 목표를 맞추는 추정치입니다."
        )

    with st.sidebar:
        st.header("1) 필수 입력")
        target_monthly_million = st.number_input(
            "희망 세후 월현금흐름 (백만원)",
            min_value=1,
            value=5,
            step=1,
            help="예: 5 입력 시 세후 월 500만원을 의미합니다.",
        )
        buffer_months = st.number_input(
            "생활비 버퍼 기간 (개월)",
            min_value=0,
            value=12,
            step=1,
            help="버퍼 현금 = 희망 월현금흐름 x 개월 수",
        )

        target_net_monthly_cf = float(target_monthly_million) * 1_000_000
        reserve_cash_preview = target_net_monthly_cf * buffer_months
        st.caption(f"예상 버퍼 현금: {format_krw(reserve_cash_preview)}")

        st.header("2) 계산 옵션")
        avoid_fin_income_comprehensive = st.toggle(
            "금융소득 종합과세(2천만원 초과) 최대한 회피",
            value=True,
            help="켜면 일반계좌 소득을 기준금액 근처로 제한하고 부족분은 매도 전략으로 전환합니다.",
        )
        use_highdiv_separate_tax = st.toggle(
            "고배당 분리과세 모델 사용",
            value=False,
            help="고배당 소득에 단순 누진세율(14/20/25/30%)을 적용합니다.",
        )
        st.toggle("해외자산 포함", value=True, disabled=True, help="요구사항에 따라 항상 포함하여 계산합니다.")

        with st.expander("3) 고급 설정 (기본값 권장)", expanded=False):
            st.caption("수익률/세율은 %로 입력합니다. (예: 15.4)")

            col_y1, col_y2 = st.columns(2)
            with col_y1:
                yield_cash_pct = st.number_input("현금성 자산 수익률 (%)", 0.0, 100.0, 3.0, 0.1)
                yield_bond_pct = st.number_input("채권 수익률 (%)", 0.0, 100.0, 4.0, 0.1)
                yield_growth_dividend_pct = st.number_input("배당성장 수익률 (%)", 0.0, 100.0, 2.5, 0.1)
            with col_y2:
                yield_highdiv_dividend_pct = st.number_input("고배당 수익률 (%)", 0.0, 100.0, 6.0, 0.1)
                withholding_tax_rate_pct = st.number_input("일반 원천징수세율 (%)", 0.0, 100.0, 15.4, 0.1)
                stt_rate_domestic_pct = st.number_input("국내 매도 거래세율 (%)", 0.0, 99.9, 0.2, 0.1)

            col_t1, col_t2 = st.columns(2)
            with col_t1:
                extra_tax_rate_on_excess_fin_income_pct = st.number_input("종합과세 추가세율 (%)", 0.0, 100.0, 26.4, 0.1)
                overseas_capgain_tax_rate_pct = st.number_input("해외 양도세율 (%)", 0.0, 100.0, 22.0, 0.1)
                isa_excess_tax_rate_pct = st.number_input("ISA 초과분 세율 (%)", 0.0, 100.0, 9.9, 0.1)
                pension_withdrawal_tax_rate_pct = st.number_input("연금계좌 과세율 (%)", 0.0, 100.0, 5.5, 0.1)
                sustainable_growth_sell_rate_pct = st.number_input("성장자산 계획매도율 (연, %)", 0.0, 100.0, 4.0, 0.1)
            with col_t2:
                fin_income_threshold = st.number_input("금융소득 종합과세 기준 (원)", 0, 20_000_000_000, 20_000_000, 1_000_000, format="%d")
                overseas_basic_deduction = st.number_input("해외 양도 기본공제 (원)", 0, 20_000_000_000, 2_500_000, 500_000, format="%d")
                isa_principal_limit = st.number_input("ISA 운용한도 가정 (원)", 0, 20_000_000_000, 200_000_000, 10_000_000, format="%d")
                isa_non_taxable_income_limit = st.number_input("ISA 비과세 소득한도 (연, 원)", 0, 20_000_000_000, 5_000_000, 500_000, format="%d")
                pension_annual_limit = st.number_input("연금 연 납입한도 가정 (원)", 0, 20_000_000_000, 18_000_000, 1_000_000, format="%d")
                pension_limit_years = st.number_input("연금 한도 반영 기간 (년)", 0, 50, 10, 1)

    assumptions = Assumptions(
        yield_cash=yield_cash_pct / 100,
        yield_bond=yield_bond_pct / 100,
        yield_growth_dividend=yield_growth_dividend_pct / 100,
        yield_highdiv_dividend=yield_highdiv_dividend_pct / 100,
        withholding_tax_rate=withholding_tax_rate_pct / 100,
        fin_income_threshold=fin_income_threshold,
        stt_rate_domestic=stt_rate_domestic_pct / 100,
        extra_tax_rate_on_excess_fin_income=extra_tax_rate_on_excess_fin_income_pct / 100,
        overseas_capgain_tax_rate=overseas_capgain_tax_rate_pct / 100,
        overseas_basic_deduction=overseas_basic_deduction,
        isa_principal_limit=float(isa_principal_limit),
        isa_non_taxable_income_limit=float(isa_non_taxable_income_limit),
        isa_excess_tax_rate=isa_excess_tax_rate_pct / 100,
        pension_annual_limit=float(pension_annual_limit),
        pension_limit_years=int(pension_limit_years),
        pension_withdrawal_tax_rate=pension_withdrawal_tax_rate_pct / 100,
        sustainable_growth_sell_rate=sustainable_growth_sell_rate_pct / 100,
    )

    try:
        result = generate_target_portfolio_recommendations(
            target_net_monthly_cf=target_net_monthly_cf,
            buffer_months=int(buffer_months),
            avoid_fin_income_comprehensive=avoid_fin_income_comprehensive,
            use_highdiv_separate_tax=use_highdiv_separate_tax,
            include_overseas_assets=True,
            assumptions=assumptions,
        )
    except ValueError as exc:
        st.error(str(exc))
        return

    st.info(
        f"계산 시각: {result.generated_at} | 모든 금액은 원 단위입니다. "
        f"| 성장자산 계획매도율 가정: 연 {assumptions.sustainable_growth_sell_rate:.1%}"
    )

    st.markdown("### 추천 결과 요약")
    overview_cols = st.columns(3)
    for col, card in zip(overview_cols, result.cards):
        required_total = _total_capital_from_card(card)
        planned_monthly = card.cashflow.net_monthly + _planned_sell_net_monthly(card, assumptions)
        col.metric(card.name, format_krw(required_total), delta=f"월 목표대응 {format_krw(planned_monthly)}")
        col.caption(f"버퍼 포함 총자산 기준, 목표: {format_krw(target_net_monthly_cf)}/월")

    st.markdown("### 포트폴리오 상세")
    tabs = st.tabs([card.name for card in result.cards])
    for tab, card in zip(tabs, result.cards):
        with tab:
            render_card(card, target_net_monthly_cf, assumptions)

    st.divider()
    json_payload = result_to_json(result)
    st.download_button(
        "결과 JSON 다운로드",
        data=json_payload,
        file_name=f"portfolio_recommendation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json",
    )

    output_path = st.text_input("JSON 파일 저장 경로", value="outputs/recommendation.json")
    if st.button("JSON 파일로 저장"):
        path = save_result_json(result, output_path)
        st.success(f"저장 완료: {path}")


if __name__ == "__main__":
    main()
