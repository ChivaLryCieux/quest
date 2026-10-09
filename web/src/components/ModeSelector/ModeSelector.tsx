import { useEffect, useRef, useState } from 'react';
import { useMarketStore } from '../../stores/marketStore';
import type { TradingMode } from '../../types';

// 模式显示配置
const MODE_CONFIG: Record<TradingMode, { label: string; dot: string }> = {
  dashboard: {
    label: 'Dashboard',
    dot: 'bg-[var(--text-muted)]',
  },
  paper: {
    label: 'Paper',
    dot: 'bg-[var(--green)]',
  },
  live: {
    label: 'Live',
    dot: 'bg-[var(--red)]',
  },
};

// 模式等级，用于单向升级过滤
const MODE_LEVEL: Record<TradingMode, number> = {
  dashboard: 0,
  paper: 1,
  live: 2,
};

const ALL_MODES: TradingMode[] = ['dashboard', 'paper', 'live'];

export function ModeSelector() {
  const tradingMode = useMarketStore((s) => s.system.trading_mode);
  const positionSize = useMarketStore((s) => s.position.size);
  const modeSwitching = useMarketStore((s) => s.modeSwitching);
  const modeSwitchError = useMarketStore((s) => s.modeSwitchError);
  const switchMode = useMarketStore((s) => s.switchMode);

  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // 点击外部关闭下拉
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const hasPosition = positionSize !== 0;
  const currentConfig = MODE_CONFIG[tradingMode];

  const handleSelect = async (target: TradingMode) => {
    // 同级或降级：仅关闭下拉
    if (MODE_LEVEL[target] <= MODE_LEVEL[tradingMode]) {
      setOpen(false);
      return;
    }

    // LIVE 二次确认（资金安全）
    if (target === 'live') {
      const ok = window.confirm(
        '⚠️ 即将切换到实盘 (LIVE) 模式\n\n实盘模式将使用真实资金进行交易。\n请确认你已配置 BINANCE_API_KEY 并了解风险。',
      );
      if (!ok) return;
    }

    setOpen(false);
    await switchMode(target as 'paper' | 'live');
  };

  const isDisabled = hasPosition || modeSwitching;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => !isDisabled && setOpen((v) => !v)}
        disabled={isDisabled}
        title={
          hasPosition
            ? '当前有持仓，禁止切换模式'
            : modeSwitching
              ? '模式切换中...'
              : '点击切换交易模式'
        }
        className={`flex items-center gap-1.5 rounded-full bg-[var(--bg-subtle)] px-3 py-1 text-xs font-medium text-[var(--text-primary)] ${
          isDisabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:bg-[#eceff3]'
        } transition-colors`}
      >
        <span className={`inline-block h-1.5 w-1.5 rounded-full ${currentConfig.dot}`} />
        {modeSwitching ? (
          <span className="inline-block h-2 w-2 animate-spin rounded-full border border-current border-t-transparent" />
        ) : null}
        {currentConfig.label}
        {!isDisabled ? <span className="text-[9px] text-[var(--text-muted)]">▾</span> : null}
      </button>

      {/* 下拉菜单 */}
      {open && !isDisabled ? (
        <div className="island absolute right-0 top-full z-50 mt-2 min-w-[180px] p-1.5">
          <div className="mb-1 border-b border-[var(--border)] px-2 py-1 text-[10px] text-[var(--text-muted)]">
            Switch mode
          </div>
          {ALL_MODES.map((mode) => {
            const config = MODE_CONFIG[mode];
            const isCurrent = mode === tradingMode;
            const isUpgrade = MODE_LEVEL[mode] > MODE_LEVEL[tradingMode];
            return (
              <button
                key={mode}
                type="button"
                onClick={() => handleSelect(mode)}
                disabled={isCurrent}
                className={`flex w-full items-center justify-between rounded-xl px-2 py-1.5 text-xs ${
                  isCurrent
                    ? 'cursor-default bg-[var(--bg-subtle)] text-[var(--text-muted)]'
                    : 'cursor-pointer text-[var(--text-primary)] hover:bg-[var(--bg-subtle)]'
                } transition-colors`}
              >
                <span className="flex items-center gap-2">
                  <span className={`inline-block h-1.5 w-1.5 rounded-full ${config.dot}`} />
                  {config.label}
                </span>
                <span className="text-[10px] text-[var(--text-muted)]">
                  {isCurrent ? '●' : isUpgrade ? '↑' : '—'}
                </span>
              </button>
            );
          })}
          <div className="mt-1 border-t border-[var(--border)] px-2 py-1 text-[10px] leading-relaxed text-[var(--text-muted)]">
            Upgrade only · locked with position
          </div>
        </div>
      ) : null}

      {/* 错误提示 */}
      {modeSwitchError ? (
        <div className="island absolute right-0 top-full z-50 mt-2 min-w-[200px] p-2 text-[11px] text-[var(--red)]">
          {modeSwitchError}
        </div>
      ) : null}
    </div>
  );
}
