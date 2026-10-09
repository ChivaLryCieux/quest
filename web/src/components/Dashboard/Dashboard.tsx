import { useMarketStore } from '../../stores/marketStore';
import { PriceHeader } from './PriceHeader';
import { PositionPanel } from '../PositionPanel/PositionPanel';
import { StrategyStatus } from '../StrategyStatus/StrategyStatus';
import { TradeHistory } from '../TradeHistory/TradeHistory';
import { AlertPanel } from '../AlertPanel/AlertPanel';
import { OrderBookPanel } from './OrderBookPanel';
import { KLineChart } from './KLineChart';

export function Dashboard() {
  const mode = useMarketStore((s) => s.account.mode?.toLowerCase() || 'dashboard');
  const isDashboardMode = mode === 'dashboard';

  return (
    <div className="flex h-full w-full gap-3 overflow-hidden">
      {/* Left island column */}
      <div className="flex h-full w-[296px] shrink-0 flex-col gap-3 overflow-y-auto pr-0.5">
        <StrategyStatus />
        <PositionPanel />
        <OrderBookPanel />
      </div>

      {/* Main island column */}
      <div className="flex h-full min-w-0 flex-1 flex-col gap-3 overflow-hidden">
        {isDashboardMode ? (
          <div className="h-full min-h-0 flex-1">
            <KLineChart />
          </div>
        ) : (
          <>
            <PriceHeader />
            <div className="min-h-0 flex-1">
              <KLineChart />
            </div>
            <div className="grid h-[176px] shrink-0 grid-cols-2 gap-3">
              <div className="h-full min-h-0 overflow-y-auto">
                <TradeHistory />
              </div>
              <div className="h-full min-h-0 overflow-y-auto">
                <AlertPanel />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
