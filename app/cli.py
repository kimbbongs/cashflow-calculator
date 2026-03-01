from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

# Ensure top-level packages (e.g., `engine`) are importable when running `python app/cli.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.models import Assumptions, InputParams
from engine.portfolio import format_krw, generate_portfolio_recommendations, save_result_json


ASSET_LABELS = {
    "reserve_cash": "버퍼 현금",
    "income_cash": "인컴-현금",
    "income_bond": "인컴-채권",
    "income_growth_dividend": "인컴-배당성장",
    "income_highdiv": "인컴-고배당",
    "growth_domestic": "성장-국내",
    "growth_overseas": "성장-해외",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="포트폴리오 추천기 CLI")
    parser.add_argument("--input-json", type=str, default="", help="입력 JSON 파일 경로")
    parser.add_argument("--total-capital", type=float, default=None, help="총자산(원)")
    parser.add_argument("--target-net-monthly-cf", type=float, default=None, help="목표 세후 월 현금흐름(원)")
    parser.add_argument("--buffer-months", type=int, default=None, help="생활비 버퍼 개월 수")

    parser.add_argument(
        "--avoid-fin-income-comprehensive",
        dest="avoid_fin_income_comprehensive",
        action="store_const",
        const=True,
        default=None,
        help="일반 금융소득 2천만원 초과를 회피하도록 계산",
    )
    parser.add_argument(
        "--allow-fin-income-comprehensive",
        dest="avoid_fin_income_comprehensive",
        action="store_const",
        const=False,
        help="일반 금융소득 초과분 추가세금까지 반영",
    )
    parser.add_argument(
        "--use-highdiv-separate-tax",
        dest="use_highdiv_separate_tax",
        action="store_const",
        const=True,
        default=None,
        help="고배당 분리과세(14/20/25/30%)를 적용",
    )
    parser.add_argument(
        "--no-highdiv-separate-tax",
        dest="use_highdiv_separate_tax",
        action="store_const",
        const=False,
        help="고배당 분리과세를 사용하지 않음",
    )
    parser.add_argument(
        "--include-overseas-assets",
        dest="include_overseas_assets",
        action="store_const",
        const=True,
        default=None,
        help="성장자산에 해외 비중 포함",
    )
    parser.add_argument(
        "--no-overseas-assets",
        dest="include_overseas_assets",
        action="store_const",
        const=False,
        help="성장자산을 국내만으로 계산",
    )

    parser.add_argument("--yield-cash", type=float, default=None)
    parser.add_argument("--yield-bond", type=float, default=None)
    parser.add_argument("--yield-growth-dividend", type=float, default=None)
    parser.add_argument("--yield-highdiv-dividend", type=float, default=None)
    parser.add_argument("--withholding-tax-rate", type=float, default=None)
    parser.add_argument("--fin-income-threshold", type=float, default=None)
    parser.add_argument("--stt-rate-domestic", type=float, default=None)
    parser.add_argument("--extra-tax-rate-on-excess-fin-income", type=float, default=None)
    parser.add_argument("--overseas-capgain-tax-rate", type=float, default=None)
    parser.add_argument("--overseas-basic-deduction", type=float, default=None)

    parser.add_argument("--output-json", type=str, default="", help="결과 JSON 저장 경로")
    return parser


def _load_input_json(path_text: str) -> Dict[str, Any]:
    path = Path(path_text)
    if not path.exists():
        raise ValueError(f"입력 JSON 파일을 찾을 수 없습니다: {path}")

    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"입력 JSON 파싱 실패: {exc}") from exc

    if not isinstance(content, dict):
        raise ValueError("입력 JSON 루트는 객체(dict)여야 합니다.")

    return content


def _pick(primary: Any, secondary: Any, default: Any) -> Any:
    if primary is not None:
        return primary
    if secondary is not None:
        return secondary
    return default


def _pick_assumption(args: argparse.Namespace, key: str, assumptions_json: Dict[str, Any], root_json: Dict[str, Any], default: Any) -> Any:
    arg_value = getattr(args, key)
    nested_value = assumptions_json.get(key)
    root_value = root_json.get(key)
    return _pick(arg_value, _pick(nested_value, root_value, None), default)


def _build_params(args: argparse.Namespace, parser: argparse.ArgumentParser) -> InputParams:
    input_json: Dict[str, Any] = {}
    if args.input_json:
        input_json = _load_input_json(args.input_json)

    assumptions_json = input_json.get("assumptions", {})
    if assumptions_json is None:
        assumptions_json = {}
    if not isinstance(assumptions_json, dict):
        raise ValueError("'assumptions'는 객체(dict)여야 합니다.")

    total_capital = _pick(args.total_capital, input_json.get("total_capital"), None)
    target_net_monthly_cf = _pick(args.target_net_monthly_cf, input_json.get("target_net_monthly_cf"), None)
    buffer_months = _pick(args.buffer_months, input_json.get("buffer_months"), 12)

    avoid_fin_income_comprehensive = _pick(
        args.avoid_fin_income_comprehensive,
        input_json.get("avoid_fin_income_comprehensive"),
        True,
    )
    use_highdiv_separate_tax = _pick(
        args.use_highdiv_separate_tax,
        input_json.get("use_highdiv_separate_tax"),
        False,
    )
    include_overseas_assets = _pick(
        args.include_overseas_assets,
        input_json.get("include_overseas_assets"),
        True,
    )

    if total_capital is None:
        parser.error("`--total-capital` 또는 input-json의 `total_capital`이 필요합니다.")
    if target_net_monthly_cf is None:
        parser.error("`--target-net-monthly-cf` 또는 input-json의 `target_net_monthly_cf`가 필요합니다.")

    assumptions = Assumptions(
        yield_cash=_pick_assumption(args, "yield_cash", assumptions_json, input_json, 0.03),
        yield_bond=_pick_assumption(args, "yield_bond", assumptions_json, input_json, 0.04),
        yield_growth_dividend=_pick_assumption(args, "yield_growth_dividend", assumptions_json, input_json, 0.025),
        yield_highdiv_dividend=_pick_assumption(args, "yield_highdiv_dividend", assumptions_json, input_json, 0.06),
        withholding_tax_rate=_pick_assumption(args, "withholding_tax_rate", assumptions_json, input_json, 0.154),
        fin_income_threshold=_pick_assumption(args, "fin_income_threshold", assumptions_json, input_json, 20_000_000),
        stt_rate_domestic=_pick_assumption(args, "stt_rate_domestic", assumptions_json, input_json, 0.002),
        extra_tax_rate_on_excess_fin_income=_pick_assumption(
            args,
            "extra_tax_rate_on_excess_fin_income",
            assumptions_json,
            input_json,
            0.264,
        ),
        overseas_capgain_tax_rate=_pick_assumption(
            args,
            "overseas_capgain_tax_rate",
            assumptions_json,
            input_json,
            0.22,
        ),
        overseas_basic_deduction=_pick_assumption(
            args,
            "overseas_basic_deduction",
            assumptions_json,
            input_json,
            2_500_000,
        ),
    )
    return InputParams(
        total_capital=total_capital,
        target_net_monthly_cf=target_net_monthly_cf,
        buffer_months=int(buffer_months),
        avoid_fin_income_comprehensive=bool(avoid_fin_income_comprehensive),
        use_highdiv_separate_tax=bool(use_highdiv_separate_tax),
        include_overseas_assets=bool(include_overseas_assets),
        assumptions=assumptions,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        params = _build_params(args, parser)
    except ValueError as exc:
        print(f"[입력 오류]\n{exc}", file=sys.stderr)
        return 1

    try:
        result = generate_portfolio_recommendations(params)
    except ValueError as exc:
        print(f"[입력 오류]\n{exc}", file=sys.stderr)
        return 1

    print("=== 포트폴리오 추천 결과 ===")
    for card in result.cards:
        print(f"\n[{card.name}] {card.profile_note}")
        print(f"- 인컴/성장 비중: {card.income_ratio:.0%} / {card.growth_ratio:.0%}")
        print(f"- 세전 월/연: {format_krw(card.cashflow.gross_monthly)} / {format_krw(card.cashflow.gross_annual)}")
        print(f"- 세후 월/연: {format_krw(card.cashflow.net_monthly)} / {format_krw(card.cashflow.net_annual)}")
        print(
            "- 목표 대비 부족분(연): "
            f"{format_krw(card.cashflow.shortfall_annual)}, "
            f"필요 매도금액(국내): {format_krw(card.cashflow.gross_sell_required)}, "
            f"거래세: {format_krw(card.cashflow.stt_cost)}"
        )
        if card.cashflow.overseas_sell_required > 0:
            print(
                "- 해외 추가 매도 추정: "
                f"{format_krw(card.cashflow.overseas_sell_required)} "
                f"(해외세 추정 {format_krw(card.cashflow.overseas_tax_estimate)})"
            )

        print("- 자산 배분:")
        for key, amount in card.asset_allocation.items():
            print(f"  {ASSET_LABELS.get(key, key)}: {format_krw(amount)}")

        print("- 계좌 비중 가이드(신규 납입 기준):")
        for key, ratio in card.account_ratio_guide.items():
            print(f"  {key}: {ratio:.0%}")

        print("- 연간 신규 납입 가이드:")
        for key, amount in card.annual_contribution_guide.items():
            print(f"  {key}: {format_krw(amount)}")

        if card.warnings:
            print("- 경고:")
            for warning in card.warnings:
                print(f"  * {warning}")

    if args.output_json:
        output_path = save_result_json(result, args.output_json)
        print(f"\nJSON 저장 완료: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
