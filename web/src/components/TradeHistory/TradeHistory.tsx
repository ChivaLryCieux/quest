import { useMarketStore } from '../../stores/marketStore';
import type { TradeRecord } from '../../types';

export function TradeHistory() {
  const trades = useMarketStore((s) => s.trades);

  return (
    <div className="island h-full p-4">
      <div className="island-title">Trades</div>

      {trades.length === 0 ? (
        <div className="py-8 text-center text-[13px] text-[var(--text-muted)]">No trades yet</div>
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full font-mono text-xs">
            <thead>
              <tr className="text-[var(--text-muted)]">
                <th className="px-1 py-2 text-left font-medium">TIME</th>
                <th className="px-1 py-2 text-left font-medium">TYPE</th>
                <th className="px-1 py-2 text-left font-medium">SIDE</th>
                <th className="px-1 py-2 text-right font-medium">PRICE</th>
                <th className="px-1 py-2 text-right font-medium">PNL</th>
                <th className="px-1 py-2 text-right font-medium">BAL</th>
              </tr>
            </thead>
            <tbody>
              {trades.slice(0, 20).map((trade, i) => (
                <TradeRow key={i} trade={trade} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TradeRow({ trade }: { trade: TradeRecord }) {
  const time = new Date(trade.time).toLocaleTimeString('en-US', { hour12: false });

  if (trade.type === 'entry') {
    return (
      <tr className="border-b border-[var(--border)] last:border-0">
        <td className="px-1 py-2 text-[var(--text-muted)]">{time}</td>
        <td className="px-1 py-2">
          <span className="rounded-full bg-[var(--bg-subtle)] px-2 py-0.5 text-[10px] text-[var(--text-secondary)]">Entry</span>
        </td>
        <td className="px-1 py-2">
          <span className={trade.side === 'LONG' ? 'text-[var(--green)]' : 'text-[var(--red)]'}>
            {trade.side}
          </span>
        </td>
        <td className="px-1 py-2 text-right text-[var(--text-secondary)]">{trade.price?.toFixed(2)}</td>
        <td className="px-1 py-2 text-right text-[var(--text-muted)]">—</td>
        <td className="px-1 py-2 text-right text-[var(--text-muted)]">—</td>
      </tr>
    );
  }

  const pnlColor = (trade.pnl ?? 0) >= 0 ? 'text-[var(--green)]' : 'text-[var(--red)]';

  return (
    <tr className="border-b border-[var(--border)] last:border-0">
      <td className="px-1 py-2 text-[var(--text-muted)]">{time}</td>
      <td className="px-1 py-2">
        <span className="rounded-full bg-[var(--bg-subtle)] px-2 py-0.5 text-[10px] text-[var(--text-secondary)]">Exit</span>
      </td>
      <td className="px-1 py-2 text-[var(--text-secondary)]">{trade.reason}</td>
      <td className="px-1 py-2 text-right text-[var(--text-secondary)]">{trade.price?.toFixed(2)}</td>
      <td className={`px-1 py-2 text-right font-medium ${pnlColor}`}>
        {(trade.pnl ?? 0) >= 0 ? '+' : ''}${trade.pnl?.toFixed(2)}
      </td>
      <td className="px-1 py-2 text-right text-[var(--text-secondary)]">
        ${trade.balance?.toFixed(2)}
      </td>
    </tr>
  );
}
