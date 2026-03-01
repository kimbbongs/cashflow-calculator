from __future__ import annotations

from numbers import Real
from typing import List

from engine.models import InputParams


def validate_inputs(params: InputParams) -> None:
    errors: List[str] = []

    if params.total_capital < 0:
        errors.append("total_capital must be >= 0.")
    if params.target_net_monthly_cf <= 0:
        errors.append("target_net_monthly_cf must be > 0.")
    if params.buffer_months < 0:
        errors.append("buffer_months must be >= 0.")

    rate_fields = (
        "yield_cash",
        "yield_bond",
        "yield_growth_dividend",
        "yield_highdiv_dividend",
        "withholding_tax_rate",
        "stt_rate_domestic",
        "extra_tax_rate_on_excess_fin_income",
        "overseas_capgain_tax_rate",
    )
    for field_name in rate_fields:
        value = getattr(params.assumptions, field_name)
        if not isinstance(value, Real):
            errors.append(f"{field_name} must be a number.")
            continue
        if not 0 <= value <= 1:
            errors.append(f"{field_name} must be between 0 and 1.")

    if params.assumptions.stt_rate_domestic >= 1:
        errors.append("stt_rate_domestic must be < 1.")

    if params.assumptions.fin_income_threshold < 0:
        errors.append("fin_income_threshold must be >= 0.")
    if params.assumptions.overseas_basic_deduction < 0:
        errors.append("overseas_basic_deduction must be >= 0.")
    if params.assumptions.isa_principal_limit < 0:
        errors.append("isa_principal_limit must be >= 0.")
    if params.assumptions.isa_non_taxable_income_limit < 0:
        errors.append("isa_non_taxable_income_limit must be >= 0.")
    if not 0 <= params.assumptions.isa_excess_tax_rate <= 1:
        errors.append("isa_excess_tax_rate must be between 0 and 1.")
    if params.assumptions.pension_annual_limit < 0:
        errors.append("pension_annual_limit must be >= 0.")
    if params.assumptions.pension_limit_years < 0:
        errors.append("pension_limit_years must be >= 0.")
    if not 0 <= params.assumptions.pension_withdrawal_tax_rate <= 1:
        errors.append("pension_withdrawal_tax_rate must be between 0 and 1.")
    if not 0 <= params.assumptions.sustainable_growth_sell_rate <= 1:
        errors.append("sustainable_growth_sell_rate must be between 0 and 1.")

    if errors:
        raise ValueError("\n".join(errors))
