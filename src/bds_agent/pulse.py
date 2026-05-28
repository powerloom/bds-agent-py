"""Pulse confluence signal detection (price move + volume burst + flow imbalance)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PulseSignal = Literal["LONG", "SHORT"] | None
PriceSource = Literal["trades", "usd"]


@dataclass
class PulseDiagnostics:
    """Per-epoch confluence metrics (for verbose logging / ops visibility)."""

    signal: PulseSignal = None
    skip_reason: str | None = None
    price_pct: float = 0.0
    burst: float = 0.0
    imbalance_pct: float = 0.0
    short_count: int = 0
    short_vol_usd: float = 0.0
    long_vol_usd: float = 0.0
    baseline_short: float = 0.0
    net_usd: float = 0.0
    price_ok: bool = False
    burst_ok: bool = False
    imbalance_ok: bool = False
    cooled_down: bool = True
    buffer_trades: int = 0


@dataclass
class PulseThresholds:
    # Looser test defaults (worksheet §3b); tighten via CLI for production.
    price_move_pct: float = 0.25
    volume_burst_mult: float = 2.0
    flow_imbalance_pct: float = 30.0
    window_seconds: int = 300
    long_window_seconds: int = 3600
    cooldown_seconds: int = 0
    min_trades: int = 5
    price_source: PriceSource = "trades"


@dataclass
class NormalizedTrade:
    ts: int
    usd: float
    side: str  # "buy" or "sell" (base token)
    price: float | None
    dedupe_key: str
    epoch_id: int | None = None


@dataclass
class PulseBuffer:
    """Rolling trade buffer for one pool (base = WETH in USDC/WETH)."""

    pool_address: str
    base_idx: int = 1  # token1 = WETH
    trades: list[NormalizedTrade] = field(default_factory=list)
    usd_samples: list[tuple[int, float]] = field(default_factory=list)  # epoch, base USD
    last_fire_ts_ms: int = 0

    def record_usd_price(self, epoch: int, usd: float) -> None:
        if usd <= 0:
            return
        self.usd_samples.append((int(epoch), float(usd)))
        if len(self.usd_samples) > 400:
            self.usd_samples = self.usd_samples[-400:]

    def ingest_epoch_trades(
        self,
        epoch_id: int,
        raw_trades: list[dict[str, Any]],
        *,
        now_ts: int | None = None,
    ) -> int:
        """Add new trades from one epoch snapshot; return count added."""
        seen = {t.dedupe_key for t in self.trades}
        added = 0
        for raw in raw_trades:
            n = normalize_trade(raw, epoch_id=epoch_id, base_idx=self.base_idx)
            if n.ts <= 0 or n.dedupe_key in seen:
                continue
            self.trades.append(n)
            seen.add(n.dedupe_key)
            added += 1
        self.trades.sort(key=lambda t: t.ts)
        cutoff = (now_ts or _now_sec()) - 3600
        self.trades = [t for t in self.trades if t.ts >= cutoff]
        return added

    def evaluate(
        self,
        thresholds: PulseThresholds,
        *,
        now_ts: int | None = None,
        now_ms: int | None = None,
    ) -> PulseDiagnostics:
        now_s = now_ts or _now_sec()
        now_m = now_ms if now_ms is not None else now_s * 1000
        diag = PulseDiagnostics(buffer_trades=len(self.trades))

        cooled_down = (now_m - self.last_fire_ts_ms) >= thresholds.cooldown_seconds * 1000
        diag.cooled_down = cooled_down

        long_med = _price_summary(
            [t for t in self.trades if t.ts >= now_s - thresholds.long_window_seconds],
            None,
        ).median
        short = _stats_over(
            self.trades,
            thresholds.window_seconds,
            now_s,
            long_med,
        )
        long_stats = _stats_over(
            self.trades,
            thresholds.long_window_seconds,
            now_s,
            long_med,
        )

        diag.short_count = short.count
        diag.short_vol_usd = short.vol_usd
        diag.long_vol_usd = long_stats.vol_usd
        diag.net_usd = short.net_usd

        if short.count < thresholds.min_trades:
            diag.skip_reason = "warming_up"
            return diag

        baseline_short = 0.0
        if long_stats.vol_usd > 0:
            baseline_short = long_stats.vol_usd * (
                thresholds.window_seconds / thresholds.long_window_seconds
            )
        diag.baseline_short = baseline_short
        if baseline_short <= 0:
            diag.skip_reason = "no_baseline"
            return diag

        price_pct = 0.0
        head_price: float | None = None
        tail_price: float | None = None
        if thresholds.price_source == "usd":
            price_pct, head_price, tail_price = _usd_price_move(
                self.usd_samples,
                thresholds.window_seconds,
                now_s,
            )
        elif short.first_price and short.last_price and short.first_price > 0:
            price_pct = ((short.last_price - short.first_price) / short.first_price) * 100.0
        burst = short.vol_usd / baseline_short if baseline_short > 0 else 0.0
        imbalance = (abs(short.net_usd) / short.vol_usd) if short.vol_usd > 0 else 0.0

        diag.price_pct = price_pct
        diag.burst = burst
        diag.imbalance_pct = imbalance * 100.0

        price_ok = abs(price_pct) >= thresholds.price_move_pct
        burst_ok = burst >= thresholds.volume_burst_mult
        imbalance_ok = diag.imbalance_pct >= thresholds.flow_imbalance_pct
        diag.price_ok = price_ok
        diag.burst_ok = burst_ok
        diag.imbalance_ok = imbalance_ok

        if not cooled_down:
            diag.skip_reason = "cooldown"
            return diag

        if not (price_ok and burst_ok and imbalance_ok):
            diag.skip_reason = "gates_failed"
            return diag

        self.last_fire_ts_ms = now_m
        diag.signal = "LONG" if short.net_usd >= 0 else "SHORT"
        diag.skip_reason = "signal"
        return diag

    def detect(
        self,
        thresholds: PulseThresholds,
        *,
        now_ts: int | None = None,
        now_ms: int | None = None,
    ) -> PulseSignal:
        return self.evaluate(thresholds, now_ts=now_ts, now_ms=now_ms).signal

    def current_price(self) -> float | None:
        if self.usd_samples:
            latest = self.usd_samples[-1][1]
            if latest > 0:
                return latest
        prices = [t.price for t in self.trades if t.price and t.price > 0]
        if not prices:
            return None
        prices.sort()
        return prices[len(prices) // 2]


@dataclass
class WindowStats:
    count: int = 0
    vol_usd: float = 0.0
    buy_usd: float = 0.0
    sell_usd: float = 0.0
    net_usd: float = 0.0
    first_price: float | None = None
    last_price: float | None = None


@dataclass
class _PriceSummary:
    median: float | None
    n: int = 0


def normalize_trade(
    trade: dict[str, Any],
    *,
    epoch_id: int,
    base_idx: int = 1,
) -> NormalizedTrade:
    data = trade.get("data") or {}
    ts = _int(data.get("block_timestamp"))
    usd = _float(data.get("calculated_trade_amount_usd"))
    amt0 = _float(data.get("calculated_token0_amount"))
    amt1 = _float(data.get("calculated_token1_amount"))
    raw0 = _float(data.get("amount0"))
    raw1 = _float(data.get("amount1"))

    sell_base = raw1 > 0 if base_idx == 1 else raw0 > 0
    side = "sell" if sell_base else "buy"

    if base_idx == 1:
        base_amt, quote_amt = abs(amt1), abs(amt0)
    else:
        base_amt, quote_amt = abs(amt0), abs(amt1)
    price = (quote_amt / base_amt) if base_amt > 0 else None

    log = trade.get("log") or {}
    tx = log.get("transactionHash") or trade.get("transactionHash") or "?"
    log_index = log.get("logIndex", 0)
    dedupe_key = f"{tx}#{log_index}"

    return NormalizedTrade(
        ts=ts,
        usd=usd,
        side=side,
        price=price,
        dedupe_key=dedupe_key,
        epoch_id=epoch_id,
    )


def _resolve_thresholds(
    thresholds: PulseThresholds | dict[str, Any] | None,
) -> PulseThresholds:
    if isinstance(thresholds, PulseThresholds):
        return thresholds
    data = dict(thresholds or {})
    return PulseThresholds(**data)


def _usd_window_epochs(window_seconds: int) -> int:
    return max(1, int(window_seconds / 12))


def _usd_price_move(
    samples: list[tuple[int, float]],
    window_seconds: int,
    now_ts: int,
) -> tuple[float, float | None, float | None]:
    """Head/tail USD move % using epoch-ordered samples (epoch ≈ block height)."""
    if len(samples) < 2:
        return 0.0, None, None
    window_epochs = _usd_window_epochs(window_seconds)
    approx_epoch = now_ts // 12 if now_ts > 1_000_000 else samples[-1][0]
    cutoff = approx_epoch - window_epochs
    win = [(e, p) for e, p in samples if e >= cutoff]
    if len(win) < 2:
        win = samples[-min(len(samples), window_epochs) :]
    if len(win) < 2:
        return 0.0, None, None
    win.sort(key=lambda x: x[0])
    third = max(1, len(win) // 3)
    head_prices = sorted(p for _, p in win[:third])
    tail_prices = sorted(p for _, p in win[-third:])
    head_med = head_prices[len(head_prices) // 2]
    tail_med = tail_prices[len(tail_prices) // 2]
    if head_med <= 0:
        return 0.0, head_med, tail_med
    pct = ((tail_med - head_med) / head_med) * 100.0
    return pct, head_med, tail_med


def detect_pulse(
    buffer: PulseBuffer,
    thresholds: PulseThresholds | dict[str, Any] | None = None,
    *,
    now_ts: int | None = None,
    now_ms: int | None = None,
) -> PulseSignal:
    """Evaluate confluence on a populated :class:`PulseBuffer`."""
    return evaluate_pulse(
        buffer,
        thresholds,
        now_ts=now_ts,
        now_ms=now_ms,
    ).signal


def evaluate_pulse(
    buffer: PulseBuffer,
    thresholds: PulseThresholds | dict[str, Any] | None = None,
    *,
    now_ts: int | None = None,
    now_ms: int | None = None,
) -> PulseDiagnostics:
    """Return confluence metrics and signal (if any) without extra stream calls."""
    th = _resolve_thresholds(thresholds)
    return buffer.evaluate(th, now_ts=now_ts, now_ms=now_ms)


def _now_sec() -> int:
    import time

    return int(time.time())


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _price_summary(
    trades: list[NormalizedTrade],
    baseline_median: float | None,
) -> _PriceSummary:
    prices = [t.price for t in trades if t.price and t.price > 0]
    if not prices:
        return _PriceSummary(median=None, n=0)
    sorted_prices = sorted(prices)
    naive_med = sorted_prices[len(sorted_prices) // 2]
    ref = baseline_median if baseline_median and baseline_median > 0 else naive_med
    filtered = [p for p in sorted_prices if ref / 5 <= p <= ref * 5]
    if not filtered:
        return _PriceSummary(median=naive_med, n=len(prices))
    med = filtered[len(filtered) // 2]
    return _PriceSummary(median=med, n=len(prices))


def _stats_over(
    trades: list[NormalizedTrade],
    window_seconds: int,
    now_ts: int,
    baseline_price_median: float | None,
) -> WindowStats:
    cutoff = now_ts - window_seconds
    win = [t for t in trades if t.ts >= cutoff]
    buy_usd = sum(t.usd for t in win if t.side == "buy")
    sell_usd = sum(t.usd for t in win if t.side == "sell")
    split1 = cutoff + window_seconds / 3
    split2 = cutoff + (2 * window_seconds) / 3
    head = [t for t in win if t.ts < split1]
    tail = [t for t in win if t.ts >= split2]
    head_med = _price_summary(head, baseline_price_median).median
    tail_med = _price_summary(tail, baseline_price_median).median
    return WindowStats(
        count=len(win),
        vol_usd=buy_usd + sell_usd,
        buy_usd=buy_usd,
        sell_usd=sell_usd,
        net_usd=buy_usd - sell_usd,
        first_price=head_med,
        last_price=tail_med,
    )
