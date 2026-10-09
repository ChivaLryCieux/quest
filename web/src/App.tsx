import { useWebSocket } from './hooks/useWebSocket';
import { useMarketStore } from './stores/marketStore';
import { Dashboard } from './components/Dashboard/Dashboard';
import { ModeSelector } from './components/ModeSelector/ModeSelector';

function App() {
  const { connected } = useWebSocket();
  const system = useMarketStore((s) => s.system);

  const hasError = system.status === 'exchange_error';

  return (
    <div className="h-screen overflow-hidden px-4 py-4 text-[var(--text-primary)]">
      {/* Floating island header */}
      <header className="island mx-auto flex max-w-[1560px] items-center justify-between px-5 py-3">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-[var(--text-primary)] text-sm font-bold text-white">
              Q
            </div>
            <h1 className="text-[15px] font-semibold tracking-wide">
              Quest
              <span className="ml-2 rounded-full bg-[var(--bg-subtle)] px-2 py-0.5 align-middle text-[10px] font-mono text-[var(--text-secondary)]">
                CTA
              </span>
            </h1>
          </div>

          <div className="h-5 w-px bg-[var(--border)]" />

          <div className="flex items-center gap-3">
            <span className="text-[13px] font-medium text-[var(--text-secondary)]">
              {useMarketStore((s) => s.account.symbol)}
            </span>
            <ModeSelector />
          </div>
        </div>

        <div className="flex items-center gap-5">
          <StatusItem connected={connected} label={`WS ${connected ? 'OK' : 'OFF'}`} />
          <StatusItem connected={system.exchange_connected} label={`EX ${system.exchange_connected ? 'OK' : 'OFF'}`} />
          <div className="text-xs font-mono text-[var(--text-muted)]">
            T+{formatUptime(system.uptime)}
          </div>
          <span className="rounded-full bg-[var(--bg-subtle)] px-2.5 py-1 text-[10px] font-mono tracking-widest text-[var(--text-secondary)]">
            {system.status.toUpperCase()}
          </span>
        </div>
      </header>

      {hasError && (
        <div className="island mx-auto mt-3 flex max-w-[1560px] items-center gap-3 px-5 py-3">
          <span className="text-[var(--red)]">●</span>
          <div>
            <div className="text-xs font-medium text-[var(--red)]">Exchange connection failed</div>
            <div className="mt-0.5 text-xs text-[var(--text-secondary)]">
              {system.error_message || 'Unable to connect to exchange. Web GUI is still running.'}
            </div>
          </div>
        </div>
      )}

      <main className="mx-auto mt-3 h-[calc(100vh-112px)] max-w-[1560px] overflow-hidden">
        <Dashboard />
      </main>
    </div>
  );
}

function StatusItem({ connected, label }: { connected: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className={`status-dot ${connected ? 'status-connected' : 'status-disconnected'}`} />
      <span className="text-xs font-mono text-[var(--text-secondary)]">{label}</span>
    </div>
  );
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h${m.toString().padStart(2, '0')}m`;
}

export default App;
