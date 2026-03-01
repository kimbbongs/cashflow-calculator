from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "assets" / "products.json"


def _to_symbol(item: dict[str, Any]) -> str | None:
    ticker = str(item.get("ticker", "")).strip()
    if not ticker or ticker == "-":
        return None

    market = str(item.get("market", "")).upper()
    if market == "KR" and ticker.isdigit() and len(ticker) == 6:
        return f"{ticker}.KS"
    return ticker


def _fetch_metrics(symbol: str) -> tuple[float | None, float | None]:
    t = yf.Ticker(symbol)

    div_yield_pct: float | None = None
    growth_1y_pct: float | None = None

    try:
        info = t.info or {}
        div_raw = info.get("trailingAnnualDividendYield") or info.get("dividendYield")
        if div_raw is not None:
            div_yield_pct = float(div_raw) * 100
    except Exception:
        pass

    if div_yield_pct is None:
        try:
            fast = t.fast_info or {}
            fast_div = fast.get("dividend_yield") or fast.get("dividendYield")
            if fast_div is not None:
                fast_div = float(fast_div)
                div_yield_pct = fast_div * 100 if fast_div <= 1 else fast_div
        except Exception:
            pass

    try:
        hist = t.history(period="1y", interval="1d", auto_adjust=True)
        if hist is not None and len(hist.index) >= 2:
            start = float(hist["Close"].iloc[0])
            end = float(hist["Close"].iloc[-1])
            if start > 0:
                growth_1y_pct = (end / start - 1) * 100
    except Exception:
        pass

    return div_yield_pct, growth_1y_pct


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def main() -> int:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"data file not found: {DATA_PATH}")

    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    presets = payload.get("presets", [])
    if not isinstance(presets, list):
        raise ValueError("`presets` must be a list")

    updated = 0
    checked = 0

    for preset in presets:
        items = preset.get("items", [])
        if not isinstance(items, list):
            continue

        for item in items:
            symbol = _to_symbol(item)
            if not symbol:
                continue

            checked += 1
            div_yield, growth_1y = _fetch_metrics(symbol)

            is_growth = bool(item.get("isGrowth"))
            if not is_growth and div_yield is not None and 0.2 <= div_yield <= 20:
                new_rate = round(div_yield, 2)
                if abs(float(item.get("rate", 0)) - new_rate) >= 0.05:
                    item["rate"] = new_rate
                    updated += 1

            if is_growth and growth_1y is not None:
                # Use bounded 1Y return as a pragmatic expected-growth proxy.
                new_growth = round(_clamp(growth_1y, 2.0, 25.0), 1)
                if abs(float(item.get("expectedGrowth", 10)) - new_growth) >= 0.5:
                    item["expectedGrowth"] = new_growth
                    updated += 1

    payload["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload["source"] = "github-actions-yfinance"
    payload["checkedSymbols"] = checked
    payload["updatedFields"] = updated

    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"checked symbols: {checked}")
    print(f"updated fields: {updated}")
    print(f"saved: {DATA_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
