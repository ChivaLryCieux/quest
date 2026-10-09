import { useEffect, useRef, useState } from 'react';
import { createChart, CandlestickSeries, HistogramSeries } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, CandlestickData, HistogramData } from 'lightweight-charts';
import { useMarketStore } from '../../stores/marketStore';

export function KLineChart() {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
   const lastCandleRef = useRef<any>(null);
   const [overlayCandle, setOverlayCandle] = useState<any>(null);

  const [timeframe, setTimeframe] = useState<'5m' | '15m' | '1h' | '1d'>('5m');
  const [switchingSymbol, setSwitchingSymbol] = useState<string | null>(null);

  const klineData = useMarketStore((s) => {
    switch (timeframe) {
      case '5m': return s.market.kline_5m;
      case '15m': return s.market.kline_15m;
      case '1h': return s.market.kline_1h;
      case '1d': return s.market.kline_1d;
      default: return s.market.kline_5m;
    }
  });
  const price = useMarketStore((s) => s.market.price);
  const symbol = useMarketStore((s) => s.account.symbol);

  const currentBaseSymbol = symbol.split('/')[0].split('-')[0].toUpperCase();

  const handleSymbolSwitch = async (sym: string) => {
    setSwitchingSymbol(sym);
    try {
      await fetch('/api/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'switch_symbol', symbol: sym }),
      });
    } catch (e) {
      console.error('Failed to switch symbol:', e);
    } finally {
      setSwitchingSymbol(null);
    }
  };

  // 1. 初始化图表
  useEffect(() => {
    if (!chartContainerRef.current) return;

    // 创建图表实例
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight || 420,
      layout: {
        background: { color: '#ffffff' },
        textColor: '#9aa3b2',
        fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      },
      grid: {
        vertLines: { color: 'rgba(17,24,39,0.04)' },
        horzLines: { color: 'rgba(17,24,39,0.04)' },
      },
      crosshair: {
        mode: 1, // Normal
        vertLine: {
          color: '#cbd2dc',
          width: 1,
          style: 3, // Dotted
          labelBackgroundColor: '#111827',
        },
        horzLine: {
          color: '#cbd2dc',
          width: 1,
          style: 3,
          labelBackgroundColor: '#111827',
        },
      },
      timeScale: {
        borderColor: 'rgba(17,24,39,0.08)',
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: 'rgba(17,24,39,0.08)',
        autoScale: true,
      },
    });

    // 创建蜡烛图系列
    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#f43f5e',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#f43f5e',
    });

    // 创建成交量图系列
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '', // 叠放在底部作为副图
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8, // 占图表底部 20% 高度
        bottom: 0,
      },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candlestickSeries;
    volumeSeriesRef.current = volumeSeries;

    // 监听容器大小自适应
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.resize(
          chartContainerRef.current.clientWidth,
          chartContainerRef.current.clientHeight || 420
        );
      }
    };
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(chartContainerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, []);

  // 周期切换时立即清空历史最后一根蜡烛缓存，防止 Tick 实时更新与历史载入产生时间戳冲突（避免图表崩溃）
  useEffect(() => {
    lastCandleRef.current = null;
    setOverlayCandle(null);
  }, [timeframe]);

  // 2. 载入历史 K 线数据
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || !klineData || klineData.length === 0) return;

    try {
      // 解析格式：[timestamp, open, high, low, close, volume]
      const formattedCandles: CandlestickData[] = [];
      const formattedVolume: HistogramData[] = [];

      // 过滤并排序，轻量图表要求时间递增且不重复
      const uniqueCandles = Array.from(
        new Map(klineData.map((item) => [Math.floor(item[0] / 1000), item])).values()
      ).sort((a, b) => a[0] - b[0]);

      uniqueCandles.forEach((item) => {
        const timeSec = Math.floor(item[0] / 1000);
        const openPrice = item[1];
        const highPrice = item[2];
        const lowPrice = item[3];
        const closePrice = item[4];
        const vol = item[5];

        formattedCandles.push({
          time: timeSec as any,
          open: openPrice,
          high: highPrice,
          low: lowPrice,
          close: closePrice,
        });

        formattedVolume.push({
          time: timeSec as any,
          value: vol,
          color: closePrice >= openPrice ? 'rgba(16, 185, 129, 0.12)' : 'rgba(244, 63, 94, 0.12)',
        });
      });

      candleSeriesRef.current.setData(formattedCandles);
      volumeSeriesRef.current.setData(formattedVolume);

      // 自适应缩放所有K线到可见区域
      if (chartRef.current) {
        chartRef.current.timeScale().fitContent();
      }

      // 保存最后一根蜡烛作为实时更新的基底并推入状态
      if (formattedCandles.length > 0) {
        const lastIndex = formattedCandles.length - 1;
        const last = {
          ...formattedCandles[lastIndex],
          volume: formattedVolume[lastIndex].value,
        };
        lastCandleRef.current = last;
        setOverlayCandle(last);
      }
    } catch (e) {
      console.error('Failed to parse kline history:', e);
    }
  }, [klineData]);

  // 3. 实时价格 Tick 更新最后一根 K 线
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || !price || !lastCandleRef.current) return;

    const last = lastCandleRef.current;
    
    // 根据当前选中的 timeframe 计算时间间隔（秒）
    let tf_sec = 300;
    if (timeframe === '15m') tf_sec = 900;
    else if (timeframe === '1h') tf_sec = 3600;
    else if (timeframe === '1d') tf_sec = 86400;

    const nowSec = Math.floor(Date.now() / 1000);
    const currentCandleTime = Math.floor(nowSec / tf_sec) * tf_sec;

    let updatedCandle: CandlestickData;

    if (currentCandleTime > last.time) {
      // 如果本地时间已经跨越到新的一根蜡烛
      updatedCandle = {
        time: currentCandleTime as any,
        open: price,
        high: price,
        low: price,
        close: price,
      };

      // 在成交量图系列里插入占位小柱子
      volumeSeriesRef.current.update({
        time: currentCandleTime as any,
        value: 0.1,
        color: 'rgba(16, 185, 129, 0.12)',
      });

      lastCandleRef.current = {
        ...updatedCandle,
        volume: 0.1,
      };
    } else {
      // 仍在当前蜡烛内，更新 High/Low/Close
      updatedCandle = {
        time: last.time,
        open: last.open,
        high: Math.max(last.high, price),
        low: Math.min(last.low, price),
        close: price,
      };

      // 更新最后一根成交量柱子的颜色与状态
      volumeSeriesRef.current.update({
        time: last.time,
        value: last.volume || 10,
        color: price >= last.open ? 'rgba(16, 185, 129, 0.12)' : 'rgba(244, 63, 94, 0.12)',
      });

      const updated = {
        ...lastCandleRef.current,
        high: updatedCandle.high,
        low: updatedCandle.low,
        close: price,
      };
      lastCandleRef.current = updated;
      setOverlayCandle(updated);
    }

    candleSeriesRef.current.update(updatedCandle);
  }, [price, timeframe]);

  return (
    <div className="island flex h-full w-full flex-col overflow-hidden p-4">
      {/* Top island toolbar */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 select-none">
        <div className="flex items-center gap-3 rounded-full bg-[var(--bg-subtle)] px-3 py-1.5">
          <span className="text-[13px] font-semibold text-[var(--text-primary)]">{symbol}</span>
          <span className="font-mono text-[10px] text-[var(--text-muted)]">{timeframe}</span>
          <div className="h-3 w-px bg-[var(--border-strong)]" />
          <span className="font-mono text-[11px] text-[var(--text-secondary)]">
            O {overlayCandle?.open?.toFixed(1) || '—'}
          </span>
          <span className="font-mono text-[11px] text-[var(--green)]">
            H {overlayCandle?.high?.toFixed(1) || '—'}
          </span>
          <span className="font-mono text-[11px] text-[var(--red)]">
            L {overlayCandle?.low?.toFixed(1) || '—'}
          </span>
          <span className="font-mono text-[11px] text-[var(--text-secondary)]">
            C {overlayCandle?.close?.toFixed(1) || '—'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex rounded-full bg-[var(--bg-subtle)] p-1">
            {['BTC', 'ETH', 'SOL'].map((sym) => {
              const isActive = currentBaseSymbol === sym;
              const isPending = switchingSymbol === sym;
              return (
                <button
                  key={sym}
                  onClick={() => !isActive && !switchingSymbol && handleSymbolSwitch(sym)}
                  disabled={!!switchingSymbol}
                  className={`rounded-full px-3 py-1 text-xs font-medium transition-all cursor-pointer ${
                    isActive
                      ? 'bg-white text-[var(--text-primary)] shadow-sm'
                      : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                  } ${isPending ? 'animate-pulse' : ''}`}
                >
                  {sym}
                </button>
              );
            })}
          </div>

          <div className="flex rounded-full bg-[var(--bg-subtle)] p-1">
            {[
              { label: '5m', value: '5m' },
              { label: '15m', value: '15m' },
              { label: '1h', value: '1h' },
              { label: '1d', value: '1d' }
            ].map((tf) => {
              const isActive = timeframe === tf.value;
              return (
                <button
                  key={tf.value}
                  onClick={() => setTimeframe(tf.value as any)}
                  className={`rounded-full px-3 py-1 font-mono text-xs transition-all cursor-pointer ${
                    isActive
                      ? 'bg-white text-[var(--text-primary)] shadow-sm'
                      : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                  }`}
                >
                  {tf.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div ref={chartContainerRef} className="min-h-0 w-full flex-1" />
    </div>
  );
}
