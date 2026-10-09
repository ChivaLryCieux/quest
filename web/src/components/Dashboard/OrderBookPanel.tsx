import { useMarketStore } from '../../stores/marketStore';

export function OrderBookPanel() {
  const orderbook = useMarketStore((s) => s.market.orderbook);

  if (!orderbook) {
    return (
      <div className="island p-4">
        <div className="island-title">Order book</div>
        <div className="py-8 text-center text-[13px] text-[var(--text-muted)]">Waiting for data</div>
      </div>
    );
  }

  const asks = orderbook.asks.slice(0, 10).reverse();
  const bids = orderbook.bids.slice(0, 10);

  const maxVol = Math.max(
    ...asks.map(([, v]) => v),
    ...bids.map(([, v]) => v)
  );

  return (
    <div className="island p-4">
      <div className="flex items-center justify-between">
        <div className="island-title">Order book</div>
        {orderbook.asks[0] && orderbook.bids[0] && (
          <div className="font-mono text-[10px] text-[var(--text-muted)]">
            {((orderbook.asks[0][0] - orderbook.bids[0][0]) / orderbook.bids[0][0] * 100).toFixed(3)}%
          </div>
        )}
      </div>

      {/* Asks */}
      <div className="mb-2 mt-3 space-y-1">
        {asks.map(([price, vol], i) => (
          <div key={i} className="relative flex justify-between py-0.5 font-mono text-xs">
            <div
              className="absolute inset-y-0 right-0 rounded bg-[var(--red)]/8"
              style={{ width: `${(vol / maxVol) * 100}%` }}
            />
            <span className="relative text-[var(--red)]">{price.toFixed(1)}</span>
            <span className="relative text-[var(--text-secondary)]">{vol.toFixed(3)}</span>
          </div>
        ))}
      </div>

      <div className="my-2 border-t border-[var(--border)]" />

      {/* Bids */}
      <div className="space-y-1">
        {bids.map(([price, vol], i) => (
          <div key={i} className="relative flex justify-between py-0.5 font-mono text-xs">
            <div
              className="absolute inset-y-0 right-0 rounded bg-[var(--green)]/8"
              style={{ width: `${(vol / maxVol) * 100}%` }}
            />
            <span className="relative text-[var(--green)]">{price.toFixed(1)}</span>
            <span className="relative text-[var(--text-secondary)]">{vol.toFixed(3)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
