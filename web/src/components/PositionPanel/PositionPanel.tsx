import { useMarketStore } from '../../stores/marketStore';

export function PositionPanel() {
  const position = useMarketStore((s) => s.position);
  const market = useMarketStore((s) => s.market);

  const hasPosition = position.size !== 0;
  const isLong = position.size > 0;

  // Calculate PnL percentage
  const pnlPct = hasPosition
    ? ((market.price - position.entry_price) / position.entry_price) * (isLong ? 1 : -1) * 100
    : 0;

  // Calculate SL/TP distance
  const slDist = hasPosition
    ? Math.abs(position.entry_price - position.sl) / position.entry_price * 100
    : 0;
  const tpDist = hasPosition
    ? Math.abs(position.tp - position.entry_price) / position.entry_price * 100
    : 0;

  return (
    <div className="island p-4">
      <div className="island-title">Position</div>

      {!hasPosition ? (
        <div className="py-7 text-center text-[13px] text-[var(--text-muted)]">No position</div>
      ) : (
        <div className="mt-3 space-y-3">
          <div className="flex items-center justify-between">
            <span
              className={`text-[15px] font-semibold ${
                isLong ? 'text-[var(--green)]' : 'text-[var(--red)]'
              }`}
            >
              {isLong ? 'Long' : 'Short'} · {position.leverage}x
            </span>
            <span className="font-mono text-[11px] text-[var(--text-muted)]">
              {Math.abs(position.size).toFixed(4)}
            </span>
          </div>

          <div
            className={`text-[18px] font-semibold tracking-tight ${
              position.unrealized_pnl >= 0 ? 'text-[var(--green)]' : 'text-[var(--red)]'
            }`}
          >
            {position.unrealized_pnl >= 0 ? '+' : ''}${position.unrealized_pnl.toFixed(2)}
            <span className="ml-2 align-middle text-xs font-normal opacity-70">
              {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="island-flat px-2.5 py-2">
              <div className="text-[10px] text-[var(--text-muted)]">Entry</div>
              <div className="mt-0.5 font-mono text-[var(--text-secondary)]">{position.entry_price.toFixed(2)}</div>
            </div>
            <div className="island-flat px-2.5 py-2">
              <div className="text-[10px] text-[var(--text-muted)]">Mark</div>
              <div className="mt-0.5 font-mono text-[var(--text-secondary)]">{market.price.toFixed(2)}</div>
            </div>
            <div className="island-flat px-2.5 py-2">
              <div className="text-[10px] text-[var(--red)]">SL · -{slDist.toFixed(2)}%</div>
              <div className="mt-0.5 font-mono text-[var(--text-secondary)]">{position.sl.toFixed(2)}</div>
            </div>
            <div className="island-flat px-2.5 py-2">
              <div className="text-[10px] text-[var(--green)]">TP · +{tpDist.toFixed(2)}%</div>
              <div className="mt-0.5 font-mono text-[var(--text-secondary)]">{position.tp.toFixed(2)}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
