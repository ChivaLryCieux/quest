import { useMarketStore } from '../../stores/marketStore';

export function StrategyStatus() {
  const strategy = useMarketStore((s) => s.strategy);

  // 市场状态映射到简洁标签
  const stateMap: Record<string, { label: string; tone: 'up' | 'down' | 'flat' }> = {
    '📈 强涨': { label: 'Strong up', tone: 'up' },
    '📈 小涨': { label: 'Mild up', tone: 'up' },
    '📉 强跌': { label: 'Strong down', tone: 'down' },
    '📉 小跌': { label: 'Mild down', tone: 'down' },
    '🦀 震荡': { label: 'Range', tone: 'flat' },
    '⏳ 等待': { label: 'Waiting', tone: 'flat' },
  };

  const stateInfo = stateMap[strategy.state] || { label: 'Unknown', tone: 'flat' as const };

  const supertrendLabel = (val: number) => {
    if (val === 1) return { text: 'Long', tone: 'up' as const };
    if (val === -1) return { text: 'Short', tone: 'down' as const };
    return { text: 'Flat', tone: 'flat' as const };
  };

  const st5 = supertrendLabel(strategy.supertrend_5m);
  const st15 = supertrendLabel(strategy.supertrend_15m);
  const st1h = supertrendLabel(strategy.supertrend_1h);

  return (
    <div className="island p-4">
      <div className="island-title">Strategy</div>

      <div className="mt-3 flex items-center justify-between">
        <div
          className={`text-[15px] font-semibold ${
            stateInfo.tone === 'up'
              ? 'text-[var(--green)]'
              : stateInfo.tone === 'down'
                ? 'text-[var(--red)]'
                : 'text-[var(--text-primary)]'
          }`}
        >
          {stateInfo.label}
        </div>
        <span className="rounded-full bg-[var(--bg-subtle)] px-2 py-0.5 text-[10px] font-mono text-[var(--text-muted)]">
          ADX {strategy.adx.toFixed(0)}
        </span>
      </div>

      <div className="mt-3 space-y-2 border-t border-[var(--border)] pt-3">
        <IndicatorRow
          label="MACD"
          value={strategy.macd.toFixed(4)}
          tone={strategy.macd >= 0 ? 'up' : 'down'}
        />
        <IndicatorRow
          label="Reversal"
          value={strategy.reversal.toFixed(2)}
          tone={strategy.reversal >= 0 ? 'up' : 'down'}
        />
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-[var(--border)] pt-3 text-xs">
        <TrendMini label="5m" info={st5} />
        <TrendMini label="15m" info={st15} />
        <TrendMini label="1h" info={st1h} />
      </div>
    </div>
  );
}

function TrendMini({ label, info }: { label: string; info: { text: string; tone: 'up' | 'down' | 'flat' } }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="font-mono text-[10px] text-[var(--text-muted)]">{label}</span>
      <span
        className={`text-xs font-medium ${
          info.tone === 'up'
            ? 'text-[var(--green)]'
            : info.tone === 'down'
              ? 'text-[var(--red)]'
              : 'text-[var(--text-muted)]'
        }`}
      >
        {info.text}
      </span>
    </div>
  );
}

function IndicatorRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'up' | 'down' | 'flat';
}) {
  const valueClass =
    tone === 'up'
      ? 'text-[var(--green)]'
      : tone === 'down'
        ? 'text-[var(--red)]'
        : 'text-[var(--text-secondary)]';

  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-[var(--text-muted)]">{label}</span>
      <span className={`font-mono text-[13px] font-medium ${valueClass}`}>{value}</span>
    </div>
  );
}
