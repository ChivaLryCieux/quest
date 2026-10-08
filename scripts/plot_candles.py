#!/usr/bin/env python3
import os
import sys
import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# =====================================================================
# 全局配置参数（方便直接修改运行）
# =====================================================================
CSV_FILE = "ETH_USDT_15m.csv"      # 数据源 CSV 文件名或路径
CANDLES_COUNT = 300                # 绘制的 K 线数量
COLOR_UP = "#c56d88"               # 上涨蜡烛颜色
COLOR_DOWN = "#fcf9f4"             # 下跌蜡烛颜色

DRAW_EMA = 0                       # 是否绘制双均线
EMA_FAST = 7                       # 快速均线周期
EMA_SLOW = 25                      # 慢速均线周期
COLOR_EMA_FAST = "#80372b"         # 快速均线颜色
COLOR_EMA_SLOW = "#2b1329"         # 慢速均线颜色

LABEL_TEXT = ""                    # 底部标签文本（留空则根据 CSV 文件名自动生成，例如 "ETH/USDT 15m"）
OUTPUT_IMAGE = "kline_chart.png"   # 保存的图片文件名或路径
# =====================================================================

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_args():
    parser = argparse.ArgumentParser(description="Quest 简易 K 线绘图工具")
    parser.add_argument("-i", "--input", type=str, default=CSV_FILE, help=f"数据源 CSV 文件路径或文件名。默认: {CSV_FILE}")
    parser.add_argument("-o", "--output", type=str, default=OUTPUT_IMAGE, help=f"保存的图片文件路径。默认保存至 output/{OUTPUT_IMAGE}")
    parser.add_argument("-n", "--count", type=int, default=CANDLES_COUNT, help=f"绘制的 K 线数量。默认: {CANDLES_COUNT}")
    return parser.parse_args()


def resolve_input_path(input_path: str) -> str:
    """自动解析输入文件路径，兼容相对路径、绝对路径及 data/historical/ 目录"""
    if os.path.isabs(input_path) and os.path.exists(input_path):
        return input_path
    if os.path.exists(input_path):
        return os.path.abspath(input_path)

    # 尝试在 data/historical/ 查找
    in_historical = os.path.join(ROOT_DIR, "data", "historical", os.path.basename(input_path))
    if os.path.exists(in_historical):
        return in_historical

    # 尝试在 data/ 查找
    in_data = os.path.join(ROOT_DIR, "data", os.path.basename(input_path))
    if os.path.exists(in_data):
        return in_data

    return input_path


def resolve_output_path(output_path: str) -> str:
    """自动解析输出路径，若仅提供文件名则默认保存到 output/ 目录"""
    if os.path.isabs(output_path):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        return output_path

    # 若指定了多级相对路径
    if os.path.dirname(output_path):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        return os.path.abspath(output_path)

    # 仅提供文件名，存入 output/
    out_dir = os.path.join(ROOT_DIR, "output")
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, output_path)


def main():
    args = parse_args()
    csv_file = resolve_input_path(args.input)
    output_image = resolve_output_path(args.output)
    candles_count = args.count

    # 1. 读取并校验 CSV 数据
    if not os.path.exists(csv_file):
        print(f"[x] 找不到数据源文件: {csv_file}")
        print("请确认是否已经使用 scripts/fetch_candles.py 获取了数据，并存入 data/historical/。")
        return

    try:
        df = pd.read_csv(csv_file)
    except Exception as e:
        print(f"[x] 读取 CSV 文件失败: {e}")
        return

    required_cols = ['open', 'high', 'low', 'close']
    for col in required_cols:
        if col not in df.columns:
            print(f"[x] 缺少必需的数据列: {col}")
            return

    # 2. 计算均线（在截取前计算，避免边缘效应）
    if DRAW_EMA:
        df['ema_fast'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()

    # 3. 截取最近的 N 根 K 线
    df_plot = df.tail(candles_count).reset_index(drop=True)
    if len(df_plot) == 0:
        print("[x] CSV 文件中无有效行数据！")
        return

    print(f"[*] 正在绘制 {len(df_plot)} 根 K 线（数据源: {csv_file}）...")

    # 4. 创建画板（纯黑背景）
    plt.rcParams['figure.facecolor'] = 'black'
    fig, ax = plt.subplots(figsize=(14, 8), facecolor='black')
    ax.set_facecolor('black')

    x = np.arange(len(df_plot))

    # 5. 绘制均线
    if DRAW_EMA:
        ax.plot(x, df_plot['ema_fast'], color=COLOR_EMA_FAST, linewidth=1.5, alpha=0.85, label=f"EMA {EMA_FAST}")
        ax.plot(x, df_plot['ema_slow'], color=COLOR_EMA_SLOW, linewidth=1.5, alpha=0.85, label=f"EMA {EMA_SLOW}")

    # 6. 绘制 K 线烛体与影线
    is_up = df_plot['close'] >= df_plot['open']
    colors = np.where(is_up, COLOR_UP, COLOR_DOWN)

    # 影线 (Wicks)
    ax.vlines(x, df_plot['low'], df_plot['high'], colors=colors, linewidth=1.2, alpha=0.9)

    # 实体 (Bodies) - 保证高度至少有一点点，防止开平价一致不显示
    heights = np.maximum(np.abs(df_plot['close'] - df_plot['open']), (df_plot['high'] - df_plot['low']) * 0.02)
    bottoms = np.minimum(df_plot['open'], df_plot['close'])

    # 用 bar 绘制烛体
    ax.bar(x, heights, bottom=bottoms, width=0.6, color=colors, edgecolor=colors, linewidth=0.5, alpha=0.95)

    # 7. 去除网格、轴框与标签，达到至简纯黑效果
    ax.axis('off')

    # 8. 添加底部轻量文字标签
    final_label = LABEL_TEXT
    if not final_label:
        base_name = os.path.basename(csv_file).replace('.csv', '')
        parts = base_name.split('_')
        if len(parts) >= 3:
            final_label = f"{parts[0]}/{parts[1]} {parts[2]}"
        else:
            final_label = base_name.replace('_', ' ')

    if final_label:
        fig.text(0.5, 0.04, final_label.upper(), color='#777777', fontsize=12,
                 ha='center', va='bottom', fontname='DejaVu Sans')

    # 9. 调整边距并保存
    plt.subplots_adjust(left=0.03, right=0.97, top=0.95, bottom=0.08)

    try:
        plt.savefig(output_image, dpi=300, facecolor='black', edgecolor='none', bbox_inches='tight')
        print(f"[+] 绘图成功！已保存至: {os.path.abspath(output_image)}")
    except Exception as e:
        print(f"[x] 保存图片失败: {e}")
    finally:
        plt.close(fig)


if __name__ == "__main__":
    main()
