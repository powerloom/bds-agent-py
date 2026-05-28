"""Multi-pool Pulse: one buffer per watched pool, pick best LONG per epoch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from bds_agent.active_markets import WatchedPool
from bds_agent.evm_swap import WETH
from bds_agent.pulse import PulseBuffer, PulseDiagnostics, PulseThresholds, evaluate_pulse

UsdPriceFetcher = Callable[[WatchedPool, int], float | None]


@dataclass
class PoolEpochResult:
    pool: WatchedPool
    added: int
    price: float | None
    diag: PulseDiagnostics
    signal: str | None


def confluence_score(diag: PulseDiagnostics, thresholds: PulseThresholds) -> float:
    """Higher = stronger LONG confluence (only meaningful when signal is LONG)."""
    if diag.signal != "LONG":
        return 0.0
    px = abs(diag.price_pct) / thresholds.price_move_pct if thresholds.price_move_pct else 0.0
    burst = diag.burst / thresholds.volume_burst_mult if thresholds.volume_burst_mult else 0.0
    imb = diag.imbalance_pct / thresholds.flow_imbalance_pct if thresholds.flow_imbalance_pct else 0.0
    return px * burst * imb


class MultiPoolTracker:
    def __init__(self, pools: list[WatchedPool]) -> None:
        self.pools: dict[str, WatchedPool] = {p.address.lower(): p for p in pools}
        self.buffers: dict[str, PulseBuffer] = {
            p.address.lower(): PulseBuffer(pool_address=p.address.lower(), base_idx=p.base_idx)
            for p in pools
        }

    def refresh_watchlist(self, pools: list[WatchedPool]) -> None:
        for p in pools:
            key = p.address.lower()
            self.pools[key] = p
            if key not in self.buffers:
                self.buffers[key] = PulseBuffer(pool_address=key, base_idx=p.base_idx)

    def ingest_snapshot(
        self,
        epoch_i: int,
        snapshot: dict[str, Any],
        thresholds: PulseThresholds,
        *,
        usd_fetcher: UsdPriceFetcher | None = None,
    ) -> list[PoolEpochResult]:
        trade_data = snapshot.get("tradeData") or {}
        if not isinstance(trade_data, dict):
            return []

        results: list[PoolEpochResult] = []
        for pool_key, pool in self.pools.items():
            raw = trade_data.get(pool.address) or trade_data.get(pool_key)
            if raw is None:
                for k, v in trade_data.items():
                    if str(k).lower() == pool_key:
                        raw = v
                        break
            if not isinstance(raw, dict):
                trades: list[dict[str, Any]] = []
            else:
                tr = raw.get("trades") or []
                trades = [x for x in tr if isinstance(x, dict)] if isinstance(tr, list) else []

            buf = self.buffers[pool_key]
            added = buf.ingest_epoch_trades(epoch_i, trades)
            if (
                thresholds.price_source == "usd"
                and usd_fetcher is not None
                and (added > 0 or not buf.usd_samples)
            ):
                usd_px = usd_fetcher(pool, epoch_i)
                if usd_px is not None:
                    buf.record_usd_price(epoch_i, usd_px)
            price = buf.current_price()
            diag = evaluate_pulse(buf, thresholds)
            results.append(
                PoolEpochResult(
                    pool=pool,
                    added=added,
                    price=price,
                    diag=diag,
                    signal=diag.signal,
                ),
            )
        return results

    @staticmethod
    def pick_best_long(
        results: list[PoolEpochResult],
        thresholds: PulseThresholds,
        *,
        prefer_alt_pools: bool = True,
    ) -> PoolEpochResult | None:
        picked = MultiPoolTracker.pick_entry_longs(
            results,
            thresholds,
            open_pools=set(),
            limit=1,
            prefer_alt_pools=prefer_alt_pools,
        )
        return picked[0] if picked else None

    @staticmethod
    def pick_entry_longs(
        results: list[PoolEpochResult],
        thresholds: PulseThresholds,
        *,
        open_pools: set[str],
        limit: int,
        prefer_alt_pools: bool = True,
        block_long_on_down_move: bool = True,
    ) -> list[PoolEpochResult]:
        """Ranked LONG candidates excluding pools already held, up to ``limit``."""
        longs = [
            r
            for r in results
            if r.signal == "LONG"
            and r.pool.address.lower() not in open_pools
            and (not block_long_on_down_move or r.diag.price_pct >= 0)
        ]
        if not longs:
            return []
        if prefer_alt_pools:
            weth = WETH.lower()
            alts = [r for r in longs if r.pool.base_token.lower() != weth]
            if alts:
                longs = alts
        longs.sort(key=lambda r: confluence_score(r.diag, thresholds), reverse=True)
        return longs[: max(0, limit)]

    def get_buffer(self, pool_address: str) -> PulseBuffer | None:
        return self.buffers.get(pool_address.lower())

    def result_for_pool(self, results: list[PoolEpochResult], pool_address: str) -> PoolEpochResult | None:
        key = pool_address.lower()
        for r in results:
            if r.pool.address.lower() == key:
                return r
        return None
