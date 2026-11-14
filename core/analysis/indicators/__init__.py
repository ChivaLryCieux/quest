"""技术指标库 (Modular Technical Indicators)

按资产价格与行情特征分为五大类：
- utils: 基础数学与平滑工具 (MathUtils)
- trend: 趋势指标 (SuperTrend, ADXCalculator, IchimokuCloud, ParabolicSAR)
- momentum: 动量与震荡指标 (MACDCalculator, KDJCalculator, StochasticRSI, CCICalculator, WilliamsPercentR)
- volatility: 波动率与通道 (BollingerBands)
- volume: 量价与流动性 (VWAPCalculator, OBVCalculator, VWMACalculator, ChaikinMoneyFlow, VolumeProfile)
"""

from .utils import MathUtils
from .volatility import BollingerBands
from .trend import (
    SuperTrend,
    ADXCalculator,
    IchimokuCloud,
    ParabolicSAR,
)
from .momentum import (
    MACDCalculator,
    KDJCalculator,
    StochasticRSI,
    CCICalculator,
    WilliamsPercentR,
)
from .volume import (
    VWAPCalculator,
    OBVCalculator,
    VWMACalculator,
    ChaikinMoneyFlow,
    VolumeProfile,
)

__all__ = [
    # Utils
    "MathUtils",
    # Volatility
    "BollingerBands",
    # Trend
    "SuperTrend",
    "ADXCalculator",
    "IchimokuCloud",
    "ParabolicSAR",
    # Momentum
    "MACDCalculator",
    "KDJCalculator",
    "StochasticRSI",
    "CCICalculator",
    "WilliamsPercentR",
    # Volume
    "VWAPCalculator",
    "OBVCalculator",
    "VWMACalculator",
    "ChaikinMoneyFlow",
    "VolumeProfile",
]
