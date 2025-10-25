# market_analyzer.py - AGGRESSIVE TRADING VERSION
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import yfinance as yf
from typing import Dict, Optional, List
import MetaTrader5 as mt5

class MarketAnalyzer:
    def __init__(self, news_api_key: str = None, te_key: str = None):
        self.news_api_key = news_api_key
        self.te_key = te_key
        self.forex_factory_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        
    def analyze_market(self, df: pd.DataFrame, symbol: str, config: dict = None) -> Dict:
        """Comprehensive market analysis dengan mode aggressive"""
        
        # Default config if not provided
        if config is None:
            config = {
                'current': {
                    'trade_mode': 'AGGRESSIVE',
                    'enable_scalping': True,
                    'enable_pattern_trading': True,
                    'enable_breakout_trading': True,
                    'ignore_economic_calendar': False,
                    'signal_threshold': 'LOW',
                    'min_signal_strength': 0.1
                }
            }
        
        analysis = {
            'technical': self._analyze_technical(df),
            'patterns': self._detect_candlestick_patterns(df),
            'breakout': self._detect_breakouts(df),
            'support_resistance': self._find_support_resistance(df),
            'scalping': self._scalping_signals(df),
            'news': self._analyze_news_simple(symbol),  # Simplified
            'calendar': self._get_economic_calendar_light(config),  # Lighter version
            'overall': {'signal': 'WAIT', 'strength': 0, 'reasons': []}
        }
        
        # Combine all analyses
        analysis['overall'] = self._combine_signals_aggressive(analysis, config)
        return analysis
    
    def _analyze_technical(self, df: pd.DataFrame) -> Dict:
        """Fast technical analysis for aggressive trading"""
        if df.empty or len(df) < 50:
            return {'signal': 'WAIT', 'signals': [], 'bullish': 0, 'bearish': 0}
        
        # Quick indicators
        df['SMA_10'] = df['close'].rolling(window=10).mean()
        df['SMA_20'] = df['close'].rolling(window=20).mean()
        df['SMA_50'] = df['close'].rolling(window=50).mean()
        df['EMA_9'] = df['close'].ewm(span=9).mean()
        df['RSI'] = self._calculate_rsi(df['close'], period=14)
        df['MACD'], df['Signal'], _ = self._calculate_macd(df['close'])
        
        # Fast Stochastic
        df['Stoch_K'], df['Stoch_D'] = self._calculate_stochastic(df, period=5)
        
        signals = []
        bullish = 0
        bearish = 0
        
        last_close = df['close'].iloc[-1]
        last_sma10 = df['SMA_10'].iloc[-1]
        last_sma20 = df['SMA_20'].iloc[-1]
        last_sma50 = df['SMA_50'].iloc[-1]
        last_rsi = df['RSI'].iloc[-1]
        last_macd = df['MACD'].iloc[-1]
        last_signal = df['Signal'].iloc[-1]
        last_stoch = df['Stoch_K'].iloc[-1]
        
        # === AGGRESSIVE SIGNALS ===
        
        # 1. Fast MA Cross
        if last_sma10 > last_sma20:
            signals.append("EMA Cross UP")
            bullish += 1
        else:
            signals.append("EMA Cross DOWN")
            bearish += 1
        
        # 2. Price Position (more sensitive)
        if last_close > last_sma10:
            bullish += 1
        else:
            bearish += 1
        
        # 3. RSI - More lenient thresholds
        if last_rsi < 40:  # Changed from 30
            signals.append(f"RSI Low ({last_rsi:.0f})")
            bullish += 2
        elif last_rsi > 60:  # Changed from 70
            signals.append(f"RSI High ({last_rsi:.0f})")
            bearish += 2
        
        # 4. MACD - Immediate signals
        if last_macd > last_signal:
            signals.append("MACD Bullish")
            bullish += 1
        else:
            signals.append("MACD Bearish")
            bearish += 1
        
        # 5. Stochastic - Fast signals
        if last_stoch < 30:
            signals.append(f"Stoch Oversold")
            bullish += 2
        elif last_stoch > 70:
            signals.append(f"Stoch Overbought")
            bearish += 2
        
        # 6. Momentum (short period)
        momentum_3 = (last_close / df['close'].iloc[-4] - 1) * 100
        if momentum_3 > 0.1:
            signals.append(f"Momentum UP ({momentum_3:+.2f}%)")
            bullish += 1
        elif momentum_3 < -0.1:
            signals.append(f"Momentum DOWN ({momentum_3:+.2f}%)")
            bearish += 1
        
        # Decision with LOW threshold
        if bullish > bearish:
            signal = 'BUY'
        elif bearish > bullish:
            signal = 'SELL'
        else:
            signal = 'WAIT'
        
        return {
            'signal': signal,
            'signals': signals,
            'bullish': bullish,
            'bearish': bearish,
            'confidence': abs(bullish - bearish) / max(bullish + bearish, 1)
        }
    
    def _detect_candlestick_patterns(self, df: pd.DataFrame) -> Dict:
        """Detect bullish/bearish candlestick patterns"""
        if len(df) < 3:
            return {'signal': 'WAIT', 'patterns': []}
        
        patterns = []
        signal = 'WAIT'
        
        # Get last 3 candles
        c0 = df.iloc[-1]  # Current
        c1 = df.iloc[-2]  # Previous
        c2 = df.iloc[-3]  # Before previous
        
        # Bullish Patterns
        
        # 1. Bullish Engulfing
        if (c1['close'] < c1['open'] and  # Previous bearish
            c0['close'] > c0['open'] and  # Current bullish
            c0['open'] < c1['close'] and
            c0['close'] > c1['open']):
            patterns.append("Bullish Engulfing (Strong Buy)")
            signal = 'BUY'
        
        # 2. Hammer
        body = abs(c0['close'] - c0['open'])
        lower_shadow = min(c0['close'], c0['open']) - c0['low']
        upper_shadow = c0['high'] - max(c0['close'], c0['open'])
        
        if lower_shadow > body * 2 and upper_shadow < body * 0.3:
            patterns.append("Hammer (Buy)")
            if signal != 'SELL':
                signal = 'BUY'
        
        # 3. Morning Star (3 candles)
        if (c2['close'] < c2['open'] and  # First bearish
            abs(c1['close'] - c1['open']) < body * 0.3 and  # Small body
            c0['close'] > c0['open'] and  # Third bullish
            c0['close'] > (c2['open'] + c2['close']) / 2):
            patterns.append("Morning Star (Strong Buy)")
            signal = 'BUY'
        
        # Bearish Patterns
        
        # 4. Bearish Engulfing
        if (c1['close'] > c1['open'] and  # Previous bullish
            c0['close'] < c0['open'] and  # Current bearish
            c0['open'] > c1['close'] and
            c0['close'] < c1['open']):
            patterns.append("Bearish Engulfing (Strong Sell)")
            signal = 'SELL'
        
        # 5. Shooting Star
        if upper_shadow > body * 2 and lower_shadow < body * 0.3:
            patterns.append("Shooting Star (Sell)")
            if signal != 'BUY':
                signal = 'SELL'
        
        # 6. Evening Star
        if (c2['close'] > c2['open'] and  # First bullish
            abs(c1['close'] - c1['open']) < body * 0.3 and  # Small body
            c0['close'] < c0['open'] and  # Third bearish
            c0['close'] < (c2['open'] + c2['close']) / 2):
            patterns.append("Evening Star (Strong Sell)")
            signal = 'SELL'
        
        # 7. Three White Soldiers (Bullish)
        if (c2['close'] > c2['open'] and
            c1['close'] > c1['open'] and
            c0['close'] > c0['open'] and
            c1['close'] > c2['close'] and
            c0['close'] > c1['close']):
            patterns.append("Three White Soldiers (Strong Buy)")
            signal = 'BUY'
        
        # 8. Three Black Crows (Bearish)
        if (c2['close'] < c2['open'] and
            c1['close'] < c1['open'] and
            c0['close'] < c0['open'] and
            c1['close'] < c2['close'] and
            c0['close'] < c1['close']):
            patterns.append("Three Black Crows (Strong Sell)")
            signal = 'SELL'
        
        return {
            'signal': signal,
            'patterns': patterns,
            'count': len(patterns)
        }
    
    def _detect_breakouts(self, df: pd.DataFrame) -> Dict:
        """Detect support/resistance breakouts"""
        if len(df) < 20:
            return {'signal': 'WAIT', 'breakouts': []}
        
        breakouts = []
        signal = 'WAIT'
        
        last_close = df['close'].iloc[-1]
        last_high = df['high'].iloc[-1]
        last_low = df['low'].iloc[-1]
        
        # Recent high/low (last 20 bars)
        recent_high = df['high'].iloc[-20:-1].max()
        recent_low = df['low'].iloc[-20:-1].min()
        
        # Breakout detection
        if last_close > recent_high:
            breakouts.append(f"Resistance Breakout at {recent_high:.5f}")
            signal = 'BUY'
        
        if last_close < recent_low:
            breakouts.append(f"Support Breakdown at {recent_low:.5f}")
            signal = 'SELL'
        
        # High volatility breakout
        atr = self._calculate_atr_value(df)
        price_range = df['high'].iloc[-1] - df['low'].iloc[-1]
        
        if price_range > atr * 1.5:
            breakouts.append("High Volatility Breakout")
            # Direction based on close position
            if df['close'].iloc[-1] > (df['high'].iloc[-1] + df['low'].iloc[-1]) / 2:
                if signal != 'SELL':
                    signal = 'BUY'
            else:
                if signal != 'BUY':
                    signal = 'SELL'
        
        return {
            'signal': signal,
            'breakouts': breakouts,
            'count': len(breakouts)
        }
    
    def _find_support_resistance(self, df: pd.DataFrame) -> Dict:
        """Find key support and resistance levels"""
        if len(df) < 50:
            return {'support': [], 'resistance': [], 'signal': 'WAIT'}
        
        # Find pivot points
        highs = df['high'].iloc[-50:]
        lows = df['low'].iloc[-50:]
        
        # Simple pivot calculation
        pivot = (df['high'].iloc[-1] + df['low'].iloc[-1] + df['close'].iloc[-1]) / 3
        
        resistance1 = 2 * pivot - lows.min()
        support1 = 2 * pivot - highs.max()
        
        resistance2 = pivot + (highs.max() - lows.min())
        support2 = pivot - (highs.max() - lows.min())
        
        current_price = df['close'].iloc[-1]
        
        signal = 'WAIT'
        
        # Signal based on proximity to S/R
        if abs(current_price - support1) / current_price < 0.002:  # Within 0.2%
            signal = 'BUY'
        elif abs(current_price - resistance1) / current_price < 0.002:
            signal = 'SELL'
        
        return {
            'support': [support2, support1],
            'resistance': [resistance1, resistance2],
            'pivot': pivot,
            'signal': signal,
            'current_price': current_price
        }
    
    def _scalping_signals(self, df: pd.DataFrame) -> Dict:
        """Fast scalping signals based on micro movements"""
        if len(df) < 10:
            return {'signal': 'WAIT', 'signals': [], 'score': 0}
        
        signals = []
        score = 0
        
        # Get recent candles
        recent = df.tail(5)
        
        # 1. Quick momentum
        momentum_1 = (recent['close'].iloc[-1] / recent['close'].iloc[-2] - 1) * 100
        if momentum_1 > 0.05:  # Even 0.05% move
            signals.append(f"Quick UP momentum ({momentum_1:+.3f}%)")
            score += 1
        elif momentum_1 < -0.05:
            signals.append(f"Quick DOWN momentum ({momentum_1:+.3f}%)")
            score -= 1
        
        # 2. Volume spike
        avg_volume = df['tick_volume'].iloc[-10:-1].mean()
        last_volume = df['tick_volume'].iloc[-1]
        
        if last_volume > avg_volume * 1.2:
            signals.append("Volume Spike")
            if momentum_1 > 0:
                score += 1
            else:
                score -= 1
        
        # 3. Consecutive moves
        consecutive_up = 0
        consecutive_down = 0
        
        for i in range(-5, 0):
            if df['close'].iloc[i] > df['close'].iloc[i-1]:
                consecutive_up += 1
            elif df['close'].iloc[i] < df['close'].iloc[i-1]:
                consecutive_down += 1
        
        if consecutive_up >= 3:
            signals.append(f"{consecutive_up} consecutive green candles")
            score += 2
        elif consecutive_down >= 3:
            signals.append(f"{consecutive_down} consecutive red candles")
            score -= 2
        
        # Decision
        if score >= 2:
            signal = 'BUY'
        elif score <= -2:
            signal = 'SELL'
        else:
            signal = 'WAIT'
        
        return {
            'signal': signal,
            'signals': signals,
            'score': score
        }
    
    def _analyze_news_simple(self, symbol: str) -> Dict:
        """Simplified news analysis - less restrictive"""
        # Skip news for faster execution in aggressive mode
        return {
            'impact': 'NEUTRAL',
            'sentiment_score': 0,
            'headlines': []
        }
    
    def _get_economic_calendar_light(self, config: dict) -> Dict:
        """Lighter economic calendar - don't block trading"""
        
        # If user wants to ignore calendar
        if config.get('current', {}).get('ignore_economic_calendar', False):
            return {
                'impact': 'LOW',
                'events': [],
                'should_reduce_confidence': False
            }
        
        # Otherwise just warn but don't block
        return {
            'impact': 'MEDIUM',
            'events': ['Economic events not blocking trades'],
            'should_reduce_confidence': False  # Don't reduce confidence!
        }
    
    def _combine_signals_aggressive(self, analysis: Dict, config: dict) -> Dict:
        """Combine signals with AGGRESSIVE strategy - more trades!"""
        
        strength = 0
        reasons = []
        
        min_threshold = config.get('current', {}).get('min_signal_strength', 0.1)
        
        # Technical: 30% (reduced from 50%)
        tech = analysis['technical']
        if tech['signal'] == 'BUY':
            strength += 0.3
            reasons.append(f"✅ Technical BUY ({tech['bullish']}/{tech['bearish']})")
        elif tech['signal'] == 'SELL':
            strength -= 0.3
            reasons.append(f"❌ Technical SELL ({tech['bearish']}/{tech['bullish']})")
        
        # Patterns: 25%
        patterns = analysis.get('patterns', {})
        if patterns.get('count', 0) > 0:
            if patterns['signal'] == 'BUY':
                strength += 0.25
                reasons.append(f"✅ Pattern: {', '.join(patterns['patterns'][:2])}")
            elif patterns['signal'] == 'SELL':
                strength -= 0.25
                reasons.append(f"❌ Pattern: {', '.join(patterns['patterns'][:2])}")
        
        # Breakout: 20%
        breakout = analysis.get('breakout', {})
        if breakout.get('count', 0) > 0:
            if breakout['signal'] == 'BUY':
                strength += 0.2
                reasons.append(f"✅ Breakout UP")
            elif breakout['signal'] == 'SELL':
                strength -= 0.2
                reasons.append(f"❌ Breakout DOWN")
        
        # Support/Resistance: 15%
        sr = analysis.get('support_resistance', {})
        if sr.get('signal') == 'BUY':
            strength += 0.15
            reasons.append(f"✅ Near Support")
        elif sr.get('signal') == 'SELL':
            strength -= 0.15
            reasons.append(f"❌ Near Resistance")
        
        # Scalping: 10%
        scalp = analysis.get('scalping', {})
        if scalp.get('score', 0) >= 2:
            strength += 0.1
            reasons.append(f"✅ Scalping signals")
        elif scalp.get('score', 0) <= -2:
            strength -= 0.1
            reasons.append(f"❌ Scalping signals")
        
        # Economic calendar - DON'T reduce strength much
        calendar = analysis.get('calendar', {})
        if calendar.get('should_reduce_confidence', False):
            strength *= 0.95  # Only 5% reduction instead of 30%
            reasons.append("⚠️ Economic event (minor impact)")
        
        # AGGRESSIVE DECISION with LOW thresholds
        abs_strength = abs(strength)
        
        trade_mode = config.get('current', {}).get('trade_mode', 'AGGRESSIVE')
        
        if trade_mode == 'SCALPING':
            # Ultra low threshold for scalping
            buy_threshold = 0.05
            sell_threshold = -0.05
        elif trade_mode == 'AGGRESSIVE':
            # Low threshold
            buy_threshold = 0.1
            sell_threshold = -0.1
        else:
            # Moderate threshold
            buy_threshold = 0.2
            sell_threshold = -0.2
        
        if strength >= buy_threshold:
            signal = 'BUY'
            reasons.append(f"🚀 BUY SIGNAL ({abs_strength:.0%})")
        elif strength <= sell_threshold:
            signal = 'SELL'
            reasons.append(f"🔻 SELL SIGNAL ({abs_strength:.0%})")
        else:
            signal = 'WAIT'
            reasons.append(f"⏸️ Signal weak ({abs_strength:.0%} < {min_threshold:.0%})")
        
        return {
            'signal': signal,
            'strength': abs_strength,
            'reasons': reasons,
            'raw_strength': strength
        }
    
    # Helper functions
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_macd(self, prices: pd.Series) -> tuple:
        exp1 = prices.ewm(span=12, adjust=False).mean()
        exp2 = prices.ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        histogram = macd - signal
        return macd, signal, histogram
    
    def _calculate_stochastic(self, df: pd.DataFrame, period: int = 14) -> tuple:
        low_min = df['low'].rolling(window=period).min()
        high_max = df['high'].rolling(window=period).max()
        stoch_k = 100 * (df['close'] - low_min) / (high_max - low_min)
        stoch_d = stoch_k.rolling(window=3).mean()
        return stoch_k, stoch_d
    
    def _calculate_atr_value(self, df: pd.DataFrame, period: int = 14) -> float:
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr = true_range.rolling(period).mean().iloc[-1]
        return atr if not pd.isna(atr) else 0.0001