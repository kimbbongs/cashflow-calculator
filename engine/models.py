from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List


@dataclass
class Assumptions:
    yield_cash: float = 0.030
    yield_bond: float = 0.040
    yield_growth_dividend: float = 0.025
    yield_highdiv_dividend: float = 0.060
    withholding_tax_rate: float = 0.154
    fin_income_threshold: float = 20_000_000
    stt_rate_domestic: float = 0.002
    extra_tax_rate_on_excess_fin_income: float = 0.264
    overseas_capgain_tax_rate: float = 0.22
    overseas_basic_deduction: float = 2_500_000
    isa_principal_limit: float = 200_000_000
    isa_non_taxable_income_limit: float = 5_000_000
    isa_excess_tax_rate: float = 0.099
    pension_annual_limit: float = 18_000_000
    pension_limit_years: int = 10
    pension_withdrawal_tax_rate: float = 0.055
    sustainable_growth_sell_rate: float = 0.04


@dataclass
class InputParams:
    total_capital: float
    target_net_monthly_cf: float
    buffer_months: int
    avoid_fin_income_comprehensive: bool = True
    use_highdiv_separate_tax: bool = False
    include_overseas_assets: bool = True
    assumptions: Assumptions = field(default_factory=Assumptions)


@dataclass
class TaxComputation:
    gross_ordinary_fin_income: float
    gross_highdiv_income: float
    taxed_ordinary_fin_income: float
    withheld_tax: float
    extra_tax_on_excess: float
    highdiv_separate_tax: float
    suppressed_ordinary_income: float
    isa_income: float = 0.0
    pension_income: float = 0.0
    general_income: float = 0.0
    isa_tax: float = 0.0
    pension_tax: float = 0.0
    total_tax: float = 0.0


@dataclass
class CashflowResult:
    gross_annual: float
    gross_monthly: float
    net_annual: float
    net_monthly: float
    target_net_annual: float
    target_net_monthly: float
    shortfall_annual: float
    gross_sell_required: float
    stt_cost: float
    overseas_sell_required: float = 0.0
    overseas_tax_estimate: float = 0.0


@dataclass
class PortfolioCard:
    profile_id: str
    name: str
    profile_note: str
    income_ratio: float
    growth_ratio: float
    growth_strategy: str
    reserve_cash: float
    asset_allocation: Dict[str, float]
    account_allocation: Dict[str, float]
    account_ratio_guide: Dict[str, float]
    annual_contribution_guide: Dict[str, float]
    tax: TaxComputation
    cashflow: CashflowResult
    warnings: List[str]


@dataclass
class RecommendationResult:
    generated_at: str
    inputs: InputParams
    cards: List[PortfolioCard]

    @classmethod
    def create(cls, inputs: InputParams, cards: List[PortfolioCard]) -> "RecommendationResult":
        return cls(
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            inputs=inputs,
            cards=cards,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
