#!/usr/bin/env python3
import os
import sys
import argparse
import pandas as pd
import ccxt
import requests
import time
from datetime import datetime, timezone, timedelta

# =====================================================================
# 全局配置参数（可以直接修改以下变量值，然后直接双击运行或 python scripts/fetch_candles.py）
# =====================================================================
SYMBOL = "ETH/USDT"         # 标的代码：Crypto 类似 BTC/USDT、SOL/USDT，A股类似 sh600519
TIMEFRAME = "1d"            # K线周期：支持 5m, 15m, 1h, 1d
LIMIT = 2880                 # 获取的 K 线数量
OUTPUT_FILE = ""            # 保存的 CSV 路径（留空则默认保存到 data/historical/ 目录）
# =====================================================================

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.config.settings import Config


def timeframe_to_ms(timeframe: str) -> int:
    """转换 K线周期字符串为毫秒数"""
    amount = int(timeframe[:-1])
    unit = timeframe[-1]
    if unit == 'm':
        return amount * 60 * 1000
    elif unit == 'h':
        return amount * 60 * 60 * 1000
    elif unit == 'd':
        return amount * 24 * 60 * 60 * 1000
    return 5 * 60 * 1000


def parse_args():
    parser = argparse.ArgumentParser(description="Quest 简易 K 线数据下载与保存工具")
    parser.add_argument("-s", "--symbol", type=str, default=SYMBOL, help=f"标的代码。默认: {SYMBOL}")
    parser.add_argument("-t", "--timeframe", type=str, default=TIMEFRAME, choices=["5m", "15m", "1h", "1d"], help=f"K线周期。默认: {TIMEFRAME}")
    parser.add_argument("-n", "--limit", type=int, default=LIMIT, help=f"获取的 K 线数量。默认: {LIMIT}")
    parser.add_argument("-o", "--output", type=str, default=OUTPUT_FILE, help="保存的 CSV 文件路径。默认自动生成并保存到 data/historical/")
    return parser.parse_args()


def fetch_domestic_history(symbol, scale, limit):
    """拉取国内新浪 A 股 K 线数据"""
    url = f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol={symbol}&scale={scale}&ma=no&datalen={limit}"
    headers = {"Referer": "https://finance.sina.com.cn/"}
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        raise Exception(f"Sina API HTTP {resp.status_code}")
    data = resp.json()
    if not isinstance(data, list):
        raise Exception(f"Sina API 返回了无效的数据结构: {data}")

    tz_bj = timezone(timedelta(hours=8))
    ohlcv = []
    for item in data:
        dt_str = item['day']
        try:
            if len(dt_str) == 10:
                dt = datetime.strptime(dt_str, "%Y-%m-%d").replace(tzinfo=tz_bj)
            else:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz_bj)
        except ValueError:
            continue

        ts = int(dt.timestamp() * 1000)
        ohlcv.append([
            ts,
            float(item['open']),
            float(item['high']),
            float(item['low']),
            float(item['close']),
            float(item['volume'])
        ])
    return ohlcv


def main():
    args = parse_args()

    symbol = args.symbol
    timeframe = args.timeframe
    limit = args.limit

    # 格式化标的
    is_domestic = symbol.lower().startswith(('sh', 'sz'))
    if not is_domestic and '/' not in symbol and '-' not in symbol:
        symbol = f"{symbol.upper()}/USDT"

    print(f"[*] 开始获取数据: 标的={symbol}, 周期={timeframe}, 数量={limit}...")

    try:
        if is_domestic:
            # A股映射周期刻度（新浪分钟数）
            scale_map = {'5m': '5', '15m': '15', '1h': '60', '1d': '240'}
            scale = scale_map.get(timeframe, '5')
            ohlcv = fetch_domestic_history(symbol, scale, limit)
        else:
            # 1. 初始化代理与 CCXT
            Config.setup_proxy()
            conf = {
                'enableRateLimit': True,
                'timeout': Config.HTTP_TIMEOUT_MS,
                'proxies': Config.exchange_proxies(),
                'options': {'defaultType': 'future'}
            }
            client = ccxt.binance(conf)
            if Config.BINANCE_REST_URL:
                client.urls['api']['fapi'] = Config.BINANCE_REST_URL

            # 2. 分页拉取历史数据（绕过单次 1500 根上限限制）
            ohlcv = []
            tf_ms = timeframe_to_ms(timeframe)
            now_ms = client.milliseconds()

            # 为了确保有足够的数据，向前多算一些（比如多预留 50 根）
            start_since = now_ms - (limit * tf_ms) - (50 * tf_ms)
            current_since = start_since

            while len(ohlcv) < limit:
                batch_limit = min(limit - len(ohlcv), 1000)
                # 向上取整拉取批次，防止缺页
                batch_limit = max(batch_limit, 500)

                print(f"[*] 正在拉取数据批次... 当前已拉取 {len(ohlcv)}/{limit} 根")
                batch = client.fetch_ohlcv(symbol, timeframe, since=current_since, limit=batch_limit)
                if not batch:
                    break

                # 去重并拼接
                if ohlcv:
                    last_ts = ohlcv[-1][0]
                    new_candles = [c for c in batch if c[0] > last_ts]
                    if not new_candles:
                        break
                    ohlcv.extend(new_candles)
                else:
                    ohlcv.extend(batch)

                # 更新下一次拉取起点
                current_since = ohlcv[-1][0] + tf_ms
                time.sleep(0.1)

            # 截取最后的 limit 根数据
            ohlcv = ohlcv[-limit:]

            if hasattr(client, 'close'):
                client.close()

        if not ohlcv:
            print("[-] 未能获取到任何 K 线数据，请检查标的名或网络连接！")
            return

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        # 补充可读时间列 (转换为东八区北京时间)
        tz_bj = timezone(timedelta(hours=8))
        df['datetime'] = df['timestamp'].apply(lambda x: datetime.fromtimestamp(x / 1000, tz=tz_bj).strftime('%Y-%m-%d %H:%M:%S'))

        # 调整列顺序
        df = df[['datetime', 'timestamp', 'open', 'high', 'low', 'close', 'volume']]
        print(f"[*] 成交量均值: {df['volume'].mean():.4f}")

        # 决定输出路径，默认保存到 data/historical/ 目录
        if args.output:
            out_file = args.output
        else:
            data_dir = os.path.join(ROOT_DIR, "data", "historical")
            os.makedirs(data_dir, exist_ok=True)
            safe_symbol = symbol.replace('/', '_').replace('-', '_')
            out_file = os.path.join(data_dir, f"{safe_symbol}_{timeframe}.csv")

        df.to_csv(out_file, index=False)
        print(f"[+] 数据获取成功！共 {len(df)} 行，已保存至: {os.path.abspath(out_file)}")

    except Exception as e:
        print(f"[x] 获取数据失败，发生错误: {e}")


if __name__ == "__main__":
    main()
