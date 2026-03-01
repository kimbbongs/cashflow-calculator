from __future__ import annotations

import pytest

from engine.models import Assumptions, InputParams
from engine.portfolio import (
    generate_portfolio_recommendations,
    generate_target_portfolio_recommendations,
    required_capital_for_target_net_monthly,
    simple_monthly_net_from_net_yield,
)
from engine.tax import calculate_net_financial_income, gross_sell_for_shortfall


def test_tc1_income_focused_monthly_math() -> None:
    # TC1: 15.1억 / 인컴 80% / 세후수익률 4.7% => 월 4,731,333원 수준
    monthly = simple_monthly_net_from_net_yield(1_510_000_000, 0.80, 0.047)
    assert monthly == pytest.approx(4_731_333.3333, rel=1e-6)


def test_tc2_required_capital_for_5m_target() -> None:
    # TC2: 동일 가정에서 월 500만원 달성 총자산은 약 15.96억(약 16억)
    capital = required_capital_for_target_net_monthly(5_000_000, 0.80, 0.047)
    assert capital == pytest.approx(1_595_744_680.851, rel=1e-6)


def test_tc3_balanced_and_growth_monthly_math() -> None:
    # TC3-a: 24.4억 / 55% / 4.5% => 월 약 503.25만원
    balanced = simple_monthly_net_from_net_yield(2_440_000_000, 0.55, 0.045)
    assert balanced == pytest.approx(5_032_500.0, rel=1e-9)

    # TC3-b: 41.7억 / 35% / 4.1% => 월 약 498.66만원
    growth = simple_monthly_net_from_net_yield(4_170_000_000, 0.35, 0.041)
    assert growth == pytest.approx(4_986_625.0, rel=1e-9)


def test_tc4_tax_and_sell_formula() -> None:
    # TC4-a: 종합과세 초과분 추가세금 계산 검증
    assumptions = Assumptions(
        withholding_tax_rate=0.154,
        fin_income_threshold=20_000_000,
        extra_tax_rate_on_excess_fin_income=0.264,
    )
    net_income, detail = calculate_net_financial_income(
        gross_ordinary_fin_income=66_000_000,
        gross_highdiv_separate_income=0,
        assumptions=assumptions,
        avoid_fin_income_comprehensive=False,
    )
    assert detail.extra_tax_on_excess == pytest.approx(12_144_000, rel=1e-9)
    assert net_income == pytest.approx(43_692_000, rel=1e-9)

    # TC4-b: 부족분 매도 공식 검증
    gross_sell, stt_cost = gross_sell_for_shortfall(1_000_000, 0.002)
    assert gross_sell == pytest.approx(1_002_004.008, rel=1e-6)
    assert stt_cost == pytest.approx(2_004.008, rel=1e-6)


def test_target_based_recommendations_build_three_profiles() -> None:
    result = generate_target_portfolio_recommendations(target_net_monthly_cf=5_000_000)
    assert [card.name for card in result.cards] == ["안정형", "밸런스형", "성장형"]
    assert all(sum(card.asset_allocation.values()) > 0 for card in result.cards)
    assert all(card.account_allocation["ISA"] >= 0 for card in result.cards)
    assert all(card.account_allocation["연금저축/IRP"] >= 0 for card in result.cards)


def test_stt_rate_must_be_less_than_one() -> None:
    params = InputParams(
        total_capital=1_000_000_000,
        target_net_monthly_cf=5_000_000,
        buffer_months=12,
        assumptions=Assumptions(stt_rate_domestic=1.0),
    )
    with pytest.raises(ValueError, match="stt_rate_domestic must be < 1"):
        generate_portfolio_recommendations(params)
