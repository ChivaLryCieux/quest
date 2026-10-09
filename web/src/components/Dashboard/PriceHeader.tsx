import { useMarketStore } from '../../stores/marketStore';

export function PriceHeader() {
  const market = useMarketStore((s) => s.market);
  const account = useMarketStore((s) => s.account);
  const position = useMarketStore((s) => s.position);

  return (
    <div className="island grid shrink-0 grid-cols-5 divide-x divide-[var(--border)] px-1 py-3">
      <HeaderCell
        label="Price"
        value={market.price.toFixed(2)}
        sub={`${market.change_24h >= 0 ? '+' : ''}${market.change_24h.toFixed(2)}%`}
        subTone={market.change_24h >= 0 ? 'up' : 'down'}
      />
      <HeaderCell label="Balance" value={`$${account.balance.toFixed(2)}`} sub={account.symbol} />
      <HeaderCell
        label="Unrealized"
        value={`${position.unrealized_pnl >= 0 ? '+' : ''}$${position.unrealized_pnl.toFixed(2)}`}
        valueTone={position.unrealized_pnl >= 0 ? 'up' : position.unrealized_pnl < 0 ? 'down' : undefined}
        sub={position.size !== 0 ? `${position.size > 0 ? 'Long' : 'Short'} ${Math.abs(position.size).toFixed(4)}` : 'Flat'}
      />
      <HeaderCell
        label="Funding"
        value={`${(market.funding_rate * 100).toFixed(4)}%`}
        sub={`BTC $${market.btc_price.toFixed(0)}`}
      />
      <div className="px-4">
        <div className="island-title">Position</div>
        {position.size !== 0 ? (
          <div className="mt-1.5 text-[13px] text-[var(--text-secondary)]">
            <span className="text-[var(--text-muted)]">EP</span> {position.entry_price.toFixed(2)}
            <span className="ml-3 text-[var(--text-muted)]">SL</span>{' '}
            <span className="text-[var(--red)]">{position.sl.toFixed(2)}</span>
            <span className="ml-3 text-[var(--text-muted)]">TP</span>{' '}
            <span className="text-[var(--green)]">{position.tp.toFixed(2)}</span>
          </div>
        ) : (
          <div className="mt-1.5 text-[13px] text-[var(--text-muted)]">No position</div>
        )}
      </div>
    </div>
  );
}

function HeaderCell({
  label,
  value,
  sub,
  subTone,
  valueTone,
}: {
  label: string;
  value: string;
  sub?: string;
  subTone?: 'up' | 'down';
  valueTone?: 'up' | 'down';
}) {
  return (
    <div className="px-4">
      <div className="island-title">{label}</div>
      <div
        className={`mt-1 text-[20px] font-semibold leading-none tracking-tight ${
          valueTone === 'up'
            ? 'text-[var(--green)]'
            : valueTone === 'down'
              ? 'text-[var(--red)]'
              : 'text-[var(--text-primary)]'
        }`}
      >
        {value}
      </div>
      {sub ? (
        <div
          className={`mt-1.5 text-xs ${
            subTone === 'up'
              ? 'text-[var(--green)]'
              : subTone === 'down'
                ? 'text-[var(--red)]'
                : 'text-[var(--text-muted)]'
          }`}
        >
          {sub}
        </div>
      ) : null}
    </div>
  );
}
