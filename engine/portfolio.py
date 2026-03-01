from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List

from engine.models import (
    Assumptions,
    InputParams,
    PortfolioCard,
    RecommendationResult,
    CashflowResult,
    TaxComputation,
)
from engine.tax import (
    calculate_net_financial_income,
    estimate_overseas_sell_tax,
    gross_sell_for_shortfall,
)
from engine.validators import validate_inputs


@dataclass(frozen=True)
class ProfileConfig:
    profile_id: str
    name: str
    profile_note: str
    income_ratio: float
    income_mix: Dict[str, float]
    overseas_growth_ratio: float
    account_ratio_guide: Dict[str, float]
    irp_risky_asset_ratio: float
    growth_strategy: str


PROFILE_CONFIGS: List[ProfileConfig] = [
    ProfileConfig(
        profile_id="stable",
        name="안정형",
        profile_note="현금흐름 안정 우선, 성장자산 매도 의존도 최소화",
        income_ratio=0.75,
        income_mix={"cash": 0.25, "bond": 0.40, "growth_dividend": 0.20, "highdiv": 0.15},
        overseas_growth_ratio=0.25,
        account_ratio_guide={"ISA": 0.20, "연금저축/IRP": 0.35, "일반계좌": 0.45},
        irp_risky_asset_ratio=0.55,
        growth_strategy="성장자산 비중을 낮춰 변동성을 줄이고, 부족분만 최소 매도",
    ),
    ProfileConfig(
        profile_id="balanced",
        name="밸런스형",
        profile_note="인컴과 성장 균형, 목표 현금흐름을 배당+매도로 혼합 달성",
        income_ratio=0.60,
        income_mix={"cash": 0.15, "bond": 0.30, "growth_dividend": 0.25, "highdiv": 0.30},
        overseas_growth_ratio=0.40,
        account_ratio_guide={"ISA": 0.18, "연금저축/IRP": 0.30, "일반계좌": 0.52},
        irp_risky_asset_ratio=0.68,
        growth_strategy="인컴 버킷과 성장 버킷을 동시에 운용하고 부족분은 계획 매도",
    ),
    ProfileConfig(
        profile_id="growth",
        name="성장형",
        profile_note="장기 성장 우선, 현금흐름 부족분은 성장자산 매도 전략 사용",
        income_ratio=0.40,
        income_mix={"cash": 0.10, "bond": 0.20, "growth_dividend": 0.30, "highdiv": 0.40},
        overseas_growth_ratio=0.55,
        account_ratio_guide={"ISA": 0.15, "연금저축/IRP": 0.25, "일반계좌": 0.60},
        irp_risky_asset_ratio=0.82,
        growth_strategy="성장자산 중심 보유 후 필요 현금흐름만 매도로 보완",
    ),
]


def simple_monthly_net_from_net_yield(total_capital: float, income_ratio: float, net_income_yield: float) -> float:
    return total_capital * income_ratio * net_income_yield / 12


def required_capital_for_target_net_monthly(
    target_net_monthly_cf: float,
    income_ratio: float,
    net_income_yield: float,
) -> float:
    if income_ratio <= 0 or net_income_yield <= 0:
        raise ValueError("income_ratio and net_income_yield must be > 0.")
    return (target_net_monthly_cf * 12) / (income_ratio * net_income_yield)


def format_krw(amount: float) -> str:
    return f"{amount:,.0f}원"


def generate_target_portfolio_recommendations(
    target_net_monthly_cf: float,
    *,
    buffer_months: int = 12,
    avoid_fin_income_comprehensive: bool = True,
    use_highdiv_separate_tax: bool = False,
    include_overseas_assets: bool = True,
    assumptions: Assumptions | None = None,
) -> RecommendationResult:
    base_params = InputParams(
        total_capital=0.0,
        target_net_monthly_cf=target_net_monthly_cf,
        buffer_months=buffer_months,
        avoid_fin_income_comprehensive=avoid_fin_income_comprehensive,
        use_highdiv_separate_tax=use_highdiv_separate_tax,
        include_overseas_assets=include_overseas_assets,
        assumptions=assumptions or Assumptions(),
    )
    validate_inputs(base_params)

    cards: List[PortfolioCard] = []
    for profile in PROFILE_CONFIGS:
        required_total_capital = _solve_total_capital_for_target(base_params, profile)
        solved_params = replace(base_params, total_capital=required_total_capital)
        cards.append(_build_card_for_total_capital(solved_params, profile, required_total_capital))

    return RecommendationResult.create(inputs=base_params, cards=cards)


def generate_portfolio_recommendations(params: InputParams) -> RecommendationResult:
    validate_inputs(params)

    reserve_cash = params.target_net_monthly_cf * params.buffer_months
    investable_capital = max(0.0, params.total_capital - reserve_cash)
    target_net_annual = params.target_net_monthly_cf * 12

    cards: List[PortfolioCard] = []
    for profile in PROFILE_CONFIGS:
        cards.append(
            _build_portfolio_card(
                params=params,
                profile=profile,
                reserve_cash=reserve_cash,
                investable_capital=investable_capital,
                target_net_annual=target_net_annual,
            )
        )

    return RecommendationResult.create(inputs=params, cards=cards)


def result_to_json(result: RecommendationResult, indent: int = 2) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=indent)


def save_result_json(result: RecommendationResult, output_path: str) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result_to_json(result), encoding="utf-8")
    return path


def _solve_total_capital_for_target(params: InputParams, profile: ProfileConfig) -> float:
    target_monthly = params.target_net_monthly_cf
    target_annual = params.target_net_monthly_cf * 12
    reserve_cash = target_monthly * params.buffer_months

    low = reserve_cash
    high = max(100_000_000.0, reserve_cash + 100_000_000.0)

    for _ in range(40):
        card = _build_card_for_total_capital(params, profile, high)
        if _target_is_satisfied(card, target_annual, params.assumptions):
            break
        high *= 2

    for _ in range(60):
        mid = (low + high) / 2
        card = _build_card_for_total_capital(params, profile, mid)
        if _target_is_satisfied(card, target_annual, params.assumptions):
            high = mid
        else:
            low = mid

    return float(max(reserve_cash, round(high / 10_000) * 10_000))


def _build_card_for_total_capital(
    params: InputParams,
    profile: ProfileConfig,
    total_capital: float,
) -> PortfolioCard:
    solved_params = replace(params, total_capital=total_capital)
    reserve_cash = solved_params.target_net_monthly_cf * solved_params.buffer_months
    investable_capital = max(0.0, solved_params.total_capital - reserve_cash)
    target_net_annual = solved_params.target_net_monthly_cf * 12
    return _build_portfolio_card(
        params=solved_params,
        profile=profile,
        reserve_cash=reserve_cash,
        investable_capital=investable_capital,
        target_net_annual=target_net_annual,
    )


def _annual_contribution_guide(assumptions: Assumptions) -> Dict[str, float]:
    return {
        "ISA_총운용한도_가정": assumptions.isa_principal_limit,
        "연금저축_IRP_연간납입한도": assumptions.pension_annual_limit,
        "연금저축_IRP_누적한도_가정": assumptions.pension_annual_limit * assumptions.pension_limit_years,
    }


def _allocate_account_amounts(
    investable_capital: float,
    profile: ProfileConfig,
    assumptions: Assumptions,
) -> tuple[Dict[str, float], Dict[str, float], Dict[str, float]]:
    desired_isa = investable_capital * profile.account_ratio_guide.get("ISA", 0.0)
    desired_pension = investable_capital * profile.account_ratio_guide.get("연금저축/IRP", 0.0)
    isa_amount = min(desired_isa, assumptions.isa_principal_limit)
    pension_limit = assumptions.pension_annual_limit * assumptions.pension_limit_years
    pension_amount = min(desired_pension, pension_limit)
    general_amount = max(0.0, investable_capital - isa_amount - pension_amount)

    account_allocation = {
        "ISA": isa_amount,
        "연금저축/IRP": pension_amount,
        "일반계좌": general_amount,
    }
    if investable_capital > 0:
        account_ratios = {k: v / investable_capital for k, v in account_allocation.items()}
    else:
        account_ratios = {k: 0.0 for k in account_allocation}

    desired_allocation = {
        "ISA": desired_isa,
        "연금저축/IRP": desired_pension,
    }
    return account_allocation, account_ratios, desired_allocation


def _calc_isa_tax(gross_isa_income: float, assumptions: Assumptions) -> float:
    if gross_isa_income <= assumptions.isa_non_taxable_income_limit:
        return 0.0
    excess_income = gross_isa_income - assumptions.isa_non_taxable_income_limit
    return excess_income * assumptions.isa_excess_tax_rate


def _estimated_sustainable_sell_net(card: PortfolioCard, assumptions: Assumptions) -> float:
    growth_domestic = card.asset_allocation.get("growth_domestic", 0.0)
    growth_overseas = card.asset_allocation.get("growth_overseas", 0.0)
    total_growth = growth_domestic + growth_overseas
    if total_growth <= 0:
        return 0.0

    planned_sell = total_growth * assumptions.sustainable_growth_sell_rate
    domestic_sell = min(planned_sell, growth_domestic)
    overseas_sell = max(0.0, planned_sell - domestic_sell)

    domestic_net = domestic_sell * (1 - assumptions.stt_rate_domestic)
    overseas_tax = estimate_overseas_sell_tax(
        sell_amount=overseas_sell,
        overseas_capgain_tax_rate=assumptions.overseas_capgain_tax_rate,
        overseas_basic_deduction=assumptions.overseas_basic_deduction,
    )
    overseas_net = max(0.0, overseas_sell - overseas_tax)
    return domestic_net + overseas_net


def _target_is_satisfied(card: PortfolioCard, target_annual: float, assumptions: Assumptions) -> bool:
    achievable_annual = card.cashflow.net_annual + _estimated_sustainable_sell_net(card, assumptions)
    return achievable_annual >= target_annual


def _build_portfolio_card(
    params: InputParams,
    profile: ProfileConfig,
    reserve_cash: float,
    investable_capital: float,
    target_net_annual: float,
) -> PortfolioCard:
    assumptions = params.assumptions

    income_capital = investable_capital * profile.income_ratio
    growth_capital = investable_capital - income_capital
    account_allocation, account_ratio_guide, desired_allocation = _allocate_account_amounts(
        investable_capital=investable_capital,
        profile=profile,
        assumptions=assumptions,
    )
    isa_share = account_ratio_guide.get("ISA", 0.0)
    pension_share = account_ratio_guide.get("연금저축/IRP", 0.0)
    general_share = account_ratio_guide.get("일반계좌", 0.0)

    income_cash = income_capital * profile.income_mix["cash"]
    income_bond = income_capital * profile.income_mix["bond"]
    income_growth_dividend = income_capital * profile.income_mix["growth_dividend"]
    income_highdiv = income_capital * profile.income_mix["highdiv"]

    if params.include_overseas_assets:
        growth_overseas = growth_capital * profile.overseas_growth_ratio
        growth_domestic = growth_capital - growth_overseas
    else:
        growth_overseas = 0.0
        growth_domestic = growth_capital

    gross_cash_income = income_cash * assumptions.yield_cash
    gross_bond_income = income_bond * assumptions.yield_bond
    gross_growth_dividend_income = income_growth_dividend * assumptions.yield_growth_dividend
    gross_highdiv_income = income_highdiv * assumptions.yield_highdiv_dividend

    gross_ordinary_fin_income = (
        gross_cash_income + gross_bond_income + gross_growth_dividend_income
    )
    gross_highdiv_separate_income = 0.0

    if params.use_highdiv_separate_tax:
        gross_highdiv_separate_income = gross_highdiv_income
    else:
        gross_ordinary_fin_income += gross_highdiv_income

    gross_income_total = gross_ordinary_fin_income + gross_highdiv_separate_income
    gross_isa_income = gross_income_total * isa_share
    gross_pension_income = gross_income_total * pension_share
    gross_general_income = gross_income_total * general_share

    ordinary_ratio = (gross_ordinary_fin_income / gross_income_total) if gross_income_total > 0 else 0.0
    general_ordinary_income = gross_general_income * ordinary_ratio
    general_highdiv_income = gross_general_income - general_ordinary_income
    if not params.use_highdiv_separate_tax:
        general_highdiv_income = 0.0
        general_ordinary_income = gross_general_income

    net_general_income_annual, general_tax = calculate_net_financial_income(
        gross_ordinary_fin_income=general_ordinary_income,
        gross_highdiv_separate_income=general_highdiv_income,
        assumptions=assumptions,
        avoid_fin_income_comprehensive=params.avoid_fin_income_comprehensive,
    )

    isa_tax = _calc_isa_tax(gross_isa_income, assumptions)
    pension_tax = gross_pension_income * assumptions.pension_withdrawal_tax_rate
    net_isa_income = gross_isa_income - isa_tax
    net_pension_income = gross_pension_income - pension_tax

    net_fin_income_annual = net_general_income_annual + net_isa_income + net_pension_income
    gross_income_annual = general_tax.taxed_ordinary_fin_income + general_highdiv_income + gross_isa_income + gross_pension_income

    tax = TaxComputation(
        gross_ordinary_fin_income=gross_ordinary_fin_income,
        gross_highdiv_income=gross_highdiv_separate_income,
        taxed_ordinary_fin_income=general_tax.taxed_ordinary_fin_income + gross_isa_income + gross_pension_income,
        withheld_tax=general_tax.withheld_tax,
        extra_tax_on_excess=general_tax.extra_tax_on_excess,
        highdiv_separate_tax=general_tax.highdiv_separate_tax,
        suppressed_ordinary_income=general_tax.suppressed_ordinary_income,
        isa_income=gross_isa_income,
        pension_income=gross_pension_income,
        general_income=gross_general_income,
        isa_tax=isa_tax,
        pension_tax=pension_tax,
        total_tax=general_tax.withheld_tax
        + general_tax.extra_tax_on_excess
        + general_tax.highdiv_separate_tax
        + isa_tax
        + pension_tax,
    )

    shortfall_annual = max(0.0, target_net_annual - net_fin_income_annual)
    gross_sell_required, stt_cost = gross_sell_for_shortfall(shortfall_annual, assumptions.stt_rate_domestic)
    planned_growth_sell_annual = (growth_domestic + growth_overseas) * assumptions.sustainable_growth_sell_rate

    overseas_sell_required = 0.0
    overseas_tax_estimate = 0.0
    if gross_sell_required > growth_domestic and params.include_overseas_assets and growth_overseas > 0:
        overseas_sell_required = min(gross_sell_required - growth_domestic, growth_overseas)
        overseas_tax_estimate = estimate_overseas_sell_tax(
            sell_amount=overseas_sell_required,
            overseas_capgain_tax_rate=assumptions.overseas_capgain_tax_rate,
            overseas_basic_deduction=assumptions.overseas_basic_deduction,
        )

    warnings: List[str] = []
    if reserve_cash > params.total_capital:
        warnings.append("버퍼 현금이 총자산보다 커서 투자 가능 금액이 0원으로 계산되었습니다.")

    if tax.general_income > assumptions.fin_income_threshold and not params.avoid_fin_income_comprehensive:
        warnings.append(
            f"일반 금융소득이 {format_krw(assumptions.fin_income_threshold)} 초과 가능: 종합과세 정산 리스크를 확인하세요."
        )

    if tax.suppressed_ordinary_income > 0:
        warnings.append(
            "종합과세 회피 토글 적용으로 일반 금융소득 일부를 인컴에서 제외하고 성장매도 전략으로 전환했습니다."
        )

    if profile.irp_risky_asset_ratio > 0.70:
        warnings.append("IRP 위험자산 비중이 70%를 초과하는 설정입니다. 규정 위반 가능성을 점검하세요.")

    if gross_sell_required > growth_domestic:
        warnings.append("필요 매도금액이 국내 성장자산 배분액을 초과합니다. 매도 전략 또는 목표치 조정이 필요합니다.")
    if shortfall_annual > 0:
        warnings.append(
            f"목표 달성을 위해 성장자산 연 {assumptions.sustainable_growth_sell_rate:.1%} "
            f"내 계획매도(약 {format_krw(planned_growth_sell_annual)}) 가정을 사용했습니다."
        )

    if params.use_highdiv_separate_tax and gross_highdiv_separate_income > 0:
        warnings.append("고배당 분리과세는 단순화된 누진구간 모델(14/20/25/30%)로 계산되었습니다.")

    if overseas_tax_estimate > 0:
        warnings.append("해외자산 매도가 필요한 경우 해외 양도세 추정치가 추가로 발생할 수 있습니다.")

    if desired_allocation["ISA"] > assumptions.isa_principal_limit:
        warnings.append(
            f"ISA는 최대 {format_krw(assumptions.isa_principal_limit)}까지 반영되고 초과분은 일반계좌로 배정되었습니다."
        )
    pension_limit = assumptions.pension_annual_limit * assumptions.pension_limit_years
    if desired_allocation["연금저축/IRP"] > pension_limit:
        warnings.append(
            f"연금저축/IRP는 누적 {format_krw(pension_limit)} 한도 가정이 적용되어 초과분은 일반계좌로 배정되었습니다."
        )

    cashflow = CashflowResult(
        gross_annual=gross_income_annual,
        gross_monthly=gross_income_annual / 12,
        net_annual=net_fin_income_annual,
        net_monthly=net_fin_income_annual / 12,
        target_net_annual=target_net_annual,
        target_net_monthly=params.target_net_monthly_cf,
        shortfall_annual=shortfall_annual,
        gross_sell_required=gross_sell_required,
        stt_cost=stt_cost,
        overseas_sell_required=overseas_sell_required,
        overseas_tax_estimate=overseas_tax_estimate,
    )

    return PortfolioCard(
        profile_id=profile.profile_id,
        name=profile.name,
        profile_note=profile.profile_note,
        income_ratio=profile.income_ratio,
        growth_ratio=1 - profile.income_ratio,
        growth_strategy=profile.growth_strategy,
        reserve_cash=reserve_cash,
        asset_allocation={
            "reserve_cash": reserve_cash,
            "income_cash": income_cash,
            "income_bond": income_bond,
            "income_growth_dividend": income_growth_dividend,
            "income_highdiv": income_highdiv,
            "growth_domestic": growth_domestic,
            "growth_overseas": growth_overseas,
        },
        account_allocation=account_allocation,
        account_ratio_guide=account_ratio_guide,
        annual_contribution_guide=_annual_contribution_guide(assumptions),
        tax=tax,
        cashflow=cashflow,
        warnings=warnings,
    )
