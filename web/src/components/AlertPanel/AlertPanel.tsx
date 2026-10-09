import { useMarketStore } from '../../stores/marketStore';
import type { AlertRecord } from '../../types';

export function AlertPanel() {
  const alerts = useMarketStore((s) => s.alerts);

  return (
    <div className="island h-full p-4">
      <div className="island-title">Alerts</div>

      {alerts.length === 0 ? (
        <div className="py-8 text-center text-[13px] text-[var(--text-muted)]">No alerts</div>
      ) : (
        <div className="mt-2 max-h-[300px] space-y-2 overflow-y-auto">
          {alerts.slice(0, 20).map((alert, i) => (
            <AlertRow
              key={i}
              alert={alert}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function AlertRow({ alert }: { alert: AlertRecord }) {
  const time = new Date(alert.time).toLocaleTimeString('en-US', { hour12: false });

  return (
    <div className="island-flat px-3 py-2.5">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[10px] text-[var(--text-muted)]">{time}</span>
        <span className="rounded-full bg-[var(--bg-subtle)] px-2 py-0.5 font-mono text-[10px] text-[var(--text-secondary)]">
          {alert.type}
        </span>
      </div>
      <div className="mt-1 truncate text-xs text-[var(--text-secondary)]">{alert.message}</div>
    </div>
  );
}
