from __future__ import annotations

from typing import List, Tuple

from engine.models import Assumptions, TaxComputation

# Simplified progressive brackets for high-dividend separate tax option.
# (Upper bound, marginal rate)
HIGH_DIV_SEPARATE_BRACKETS: List[Tuple[float, float]] = [
    (20_000_000, 0.14),
    (50_000_000, 0.20),
    (100_000_000, 0.25),
    (float("inf"), 0.30),
]


def calc_highdiv_separate_tax(gross_highdiv_income: float) -> float:
    if gross_highdiv_income <= 0:
        return 0.0

    tax = 0.0
    lower_bound = 0.0
    remaining = gross_highdiv_income

    for upper_bound, rate in HIGH_DIV_SEPARATE_BRACKETS:
        bracket_width = upper_bound - lower_bound
        taxable = min(remaining, bracket_width)
        if taxable <= 0:
            break

        tax += taxable * rate
        remaining -= taxable
        lower_bound = upper_bound

    return tax


def calculate_net_financial_income(
    gross_ordinary_fin_income: float,
    gross_highdiv_separate_income: float,
    assumptions: Assumptions,
    avoid_fin_income_comprehensive: bool,
) -> tuple[float, TaxComputation]:
    taxed_ordinary_fin_income = gross_ordinary_fin_income
    suppressed_ordinary_income = 0.0

    # If the user wants to avoid comprehensive taxation, cap ordinary fin income at threshold.
    if avoid_fin_income_comprehensive and gross_ordinary_fin_income > assumptions.fin_income_threshold:
        taxed_ordinary_fin_income = assumptions.fin_income_threshold
        suppressed_ordinary_income = gross_ordinary_fin_income - taxed_ordinary_fin_income

    withheld_tax = taxed_ordinary_fin_income * assumptions.withholding_tax_rate

    extra_tax_on_excess = 0.0
    if not avoid_fin_income_comprehensive:
        excess_fin_income = max(0.0, taxed_ordinary_fin_income - assumptions.fin_income_threshold)
        extra_tax_on_excess = excess_fin_income * assumptions.extra_tax_rate_on_excess_fin_income

    net_ordinary_income = taxed_ordinary_fin_income - withheld_tax - extra_tax_on_excess

    highdiv_separate_tax = calc_highdiv_separate_tax(gross_highdiv_separate_income)
    net_highdiv_income = gross_highdiv_separate_income - highdiv_separate_tax

    tax = TaxComputation(
        gross_ordinary_fin_income=gross_ordinary_fin_income,
        gross_highdiv_income=gross_highdiv_separate_income,
        taxed_ordinary_fin_income=taxed_ordinary_fin_income,
        withheld_tax=withheld_tax,
        extra_tax_on_excess=extra_tax_on_excess,
        highdiv_separate_tax=highdiv_separate_tax,
        suppressed_ordinary_income=suppressed_ordinary_income,
    )

    return net_ordinary_income + net_highdiv_income, tax


def gross_sell_for_shortfall(shortfall_net_amount: float, stt_rate_domestic: float) -> tuple[float, float]:
    if shortfall_net_amount <= 0:
        return 0.0, 0.0

    gross_sell = shortfall_net_amount / (1 - stt_rate_domestic)
    stt_cost = gross_sell * stt_rate_domestic
    return gross_sell, stt_cost


def estimate_overseas_sell_tax(
    sell_amount: float,
    overseas_capgain_tax_rate: float,
    overseas_basic_deduction: float,
) -> float:
    if sell_amount <= 0:
        return 0.0

    taxable_base = max(0.0, sell_amount - overseas_basic_deduction)
    return taxable_base * overseas_capgain_tax_rate

