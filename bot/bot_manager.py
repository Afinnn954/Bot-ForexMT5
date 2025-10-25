# bot/bot_manager.py - FIXED VERSION WITH LIMITS
from typing import Dict, Optional, List
import time
from datetime import datetime
import MetaTrader5 as mt5
import pandas as pd
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

class TradingBot:
    def __init__(self, config: Dict, analyzer, trader, gemini_client=None):
        self.config = config
        self.analyzer = analyzer
        self.trader = trader
        self.gemini_client = gemini_client
        self.running = False
        self.last_analysis_time = 0
        
        # Initialize counters
        self.trades_today = 0
        self.last_trade_date = datetime.now().date()
        
        # Get account info for balance tracking
        account = mt5.account_info()
        if account:
            self.starting_balance = account.balance
            # Save to config if not set
            if config.get('current', {}).get('starting_balance', 0) == 0:
                config['current']['starting_balance'] = account.balance
        else:
            self.starting_balance = config.get('current', {}).get('starting_balance', 100)
        
        # Multi-position settings
        self.max_daily_trades = config.get('current', {}).get('max_daily_trades', 100)
        self.max_positions_per_symbol = config.get('current', {}).get('max_positions_per_symbol', 3)
        self.max_total_positions = config.get('current', {}).get('max_total_positions', 10)
        
        # Multi-symbol/timeframe
        self.enable_multi_symbol = config.get('current', {}).get('enable_multi_symbol', False)
        self.enable_multi_timeframe = config.get('current', {}).get('enable_multi_timeframe', False)
        self.symbols_to_trade = config.get('current', {}).get('symbols_to_trade', [config['current']['symbol']])
        self.timeframes_to_check = config.get('current', {}).get('timeframes_to_check', ['M5'])
        
        # Rapid fire mode
        self.rapid_fire_mode = config.get('current', {}).get('rapid_fire_mode', False)
        
        # Grid trading
        self.grid_trading = config.get('current', {}).get('grid_trading', False)
        self.grid_distance = config.get('current', {}).get('grid_distance', 5.0)
        self.max_grid_levels = config.get('current', {}).get('max_grid_levels', 3)
        
        # Dynamic lot sizing
        self.dynamic_lot_sizing = config.get('current', {}).get('dynamic_lot_sizing', False)
        self.risk_percent = config.get('current', {}).get('risk_percent_per_trade', 1.0)
        
        # Check interval
        self.check_interval = config.get('current', {}).get('auto_analyze_interval', 1) * 60
        
        if self.rapid_fire_mode:
            self.check_interval = 10  # Check every 10 seconds in rapid fire mode
        
        print(f"🤖 Bot initialized - RAPID FIRE MODE:")
        print(f"   Starting Balance: ${self.starting_balance:.2f}")
        print(f"   Max trades/day: {self.max_daily_trades}")
        print(f"   Max positions per symbol: {self.max_positions_per_symbol}")
        print(f"   Max total positions: {self.max_total_positions}")
        print(f"   Auto-close profit: ${config.get('current', {}).get('auto_close_target', 0.4):.2f}")
        print(f"   Check interval: {self.check_interval}s")
        print(f"   Multi-symbol: {'✅' if self.enable_multi_symbol else '❌'}")
        print(f"   Dynamic lot sizing: {'✅' if self.dynamic_lot_sizing else '❌'}")
        print(f"   Rapid fire: {'✅' if self.rapid_fire_mode else '❌'}")
        
    def start(self) -> None:
        """Start the trading bot"""
        self.running = True
        
        print(f"\n🚀 RAPID FIRE Bot Started!")
        print(f"⚡ Symbols: {', '.join(self.symbols_to_trade)}")
        print(f"⏱️ Checking every {self.check_interval}s")
        print(f"🛑 MAX {self.max_total_positions} POSITIONS - Will STOP when full!")
        print("Press Ctrl+C to stop\n")
        
        while self.running:
            try:
                # Reset daily counter if new day
                self._check_new_day()
                
                # ALWAYS manage positions first (for auto-close)
                self.trader.manage_open_positions()
                
                # Run trading cycle
                if self.rapid_fire_mode:
                    self._run_rapid_fire_cycle()
                else:
                    self._run_cycle()
                
                # Wait before next cycle
                time.sleep(self.check_interval)
                
            except KeyboardInterrupt:
                print("\n⏹️ Stopping bot...")
                self.stop()
                break
                
            except Exception as e:
                print(f"❌ Cycle error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(10)
    
    def stop(self) -> None:
        """Stop the trading bot"""
        self.running = False
        
        # Get final stats
        positions = self._get_current_positions()
        open_count = len(positions)
        
        total_profit = sum(p.profit for p in positions)
        
        account = mt5.account_info()
        if account:
            current_balance = account.balance
            profit_from_start = current_balance - self.starting_balance
        else:
            profit_from_start = 0
        
        print(f"\n🛑 Bot stopped")
        print(f"📊 Final stats:")
        print(f"   Starting balance: ${self.starting_balance:.2f}")
        print(f"   Current balance: ${account.balance:.2f}" if account else "")
        print(f"   Profit/Loss: ${profit_from_start:+.2f}")
        print(f"   Trades executed: {self.trades_today}/{self.max_daily_trades}")
        print(f"   Open positions: {open_count}")
        print(f"   Floating P/L: ${total_profit:+.2f}")
    
    def _check_new_day(self) -> None:
        """Reset counter if new trading day"""
        current_date = datetime.now().date()
        
        if current_date > self.last_trade_date:
            print(f"\n📅 New trading day")
            print(f"   Yesterday's trades: {self.trades_today}")
            self.trades_today = 0
            self.last_trade_date = current_date
    
    def _run_rapid_fire_cycle(self) -> None:
        """Rapid fire mode - CHECK LIMITS FIRST"""
        try:
            # 1. Manage existing positions (auto-close profit, BEP, trailing)
            self.trader.manage_open_positions()
            
            # 2. Get current positions
            current_positions = self._get_current_positions()
            total_open = len(current_positions)
            
            # 3. CHECK MAX POSITIONS LIMIT - STOP IF FULL!
            if total_open >= self.max_total_positions:
                timestamp = datetime.now().strftime('%H:%M:%S')
                print(f"[{timestamp}] ⚠️ MAX POSITIONS REACHED ({total_open}/{self.max_total_positions}) - Waiting for close...")
                
                # Show current positions status
                if total_open > 0:
                    total_profit = sum(p.profit for p in current_positions)
                    print(f"           Open P/L: ${total_profit:+.2f} | Target: ${self.config['current']['auto_close_target']:.2f}")
                    
                    # Show individual positions
                    for p in current_positions[:3]:  # Show top 3
                        print(f"           {p.symbol} {p.type} | Profit: ${p.profit:+.2f}")
                    
                    if total_open > 3:
                        print(f"           ... and {total_open - 3} more")
                
                return  # DON'T OPEN NEW POSITIONS!
            
            # 4. Check daily limit
            if self.trades_today >= self.max_daily_trades:
                print(f"⚠️ Daily limit reached ({self.trades_today}/{self.max_daily_trades})")
                return
            
            # 5. Get symbols to analyze
            symbols = self.symbols_to_trade if self.enable_multi_symbol else [self.config['current']['symbol']]
            
            # 6. Calculate how many new positions we can open
            remaining_slots = self.max_total_positions - total_open
            
            if remaining_slots <= 0:
                return  # No slots available
            
            # 7. Analyze all symbols in parallel
            timestamp = datetime.now().strftime('%H:%M:%S')
            print(f"\n[{timestamp}] Analyzing {len(symbols)} symbols | Positions: {total_open}/{self.max_total_positions} | Slots: {remaining_slots}")
            
            signals = []
            
            # Use ThreadPoolExecutor for parallel analysis
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {}
                
                for symbol in symbols:
                    # Check per-symbol limit
                    symbol_positions = len([p for p in current_positions if p.symbol == symbol])
                    if symbol_positions >= self.max_positions_per_symbol:
                        continue
                    
                    # Submit analysis tasks
                    if self.enable_multi_timeframe:
                        for tf in self.timeframes_to_check:
                            future = executor.submit(self._analyze_symbol_timeframe, symbol, tf)
                            futures[future] = (symbol, tf)
                    else:
                        tf = self.config['current']['timeframe']
                        future = executor.submit(self._analyze_symbol_timeframe, symbol, tf)
                        futures[future] = (symbol, tf)
                
                # Collect results
                for future in as_completed(futures):
                    symbol, tf = futures[future]
                    try:
                        result = future.result()
                        if result and result['signal'] != 'WAIT':
                            signals.append(result)
                    except Exception as e:
                        pass  # Silently skip errors
            
            # 8. Display findings
            if len(signals) > 0:
                print(f"   Found {len(signals)} signals")
            
            # 9. Execute signals (up to remaining slots)
            if signals and remaining_slots > 0:
                # Sort by strength
                signals.sort(key=lambda x: x['strength'], reverse=True)
                
                # Limit to remaining slots
                signals_to_execute = signals[:remaining_slots]
                
                print(f"   Executing top {len(signals_to_execute)} signal(s)...")
                
                # Execute
                executed = 0
                for signal in signals_to_execute:
                    if self._execute_signal(signal):
                        executed += 1
                        
                        # Check if we're full now
                        current_total = len(self._get_current_positions())
                        if current_total >= self.max_total_positions:
                            print(f"\n🔴 MAX POSITIONS REACHED - Stopping new orders!")
                            break
                        
                        # Small delay between orders
                        if executed < len(signals_to_execute):
                            time.sleep(0.5)
                
                if executed > 0:
                    print(f"   ✅ Opened {executed} new position(s)")
            
        except Exception as e:
            print(f"❌ Rapid fire cycle error: {e}")
            import traceback
            traceback.print_exc()
    
    def _analyze_symbol_timeframe(self, symbol: str, timeframe: str) -> Optional[Dict]:
        """Analyze a single symbol/timeframe combination"""
        try:
            # Get data
            df = self._get_market_data_for(symbol, timeframe)
            if df.empty:
                return None
            
            # Analyze
            analysis = self.analyzer.analyze_market(df, symbol, self.config)
            
            signal = analysis['overall']['signal']
            strength = analysis['overall']['strength']
            
            if signal != 'WAIT':
                return {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'signal': signal,
                    'strength': strength,
                    'analysis': analysis
                }
            
            return None
            
        except Exception as e:
            return None
    
    def _execute_signal(self, signal_data: Dict) -> bool:
        """Execute a trading signal"""
        try:
            symbol = signal_data['symbol']
            action = signal_data['signal']
            strength = signal_data['strength']
            tf = signal_data['timeframe']
            
            print(f"\n{'='*60}")
            print(f"💰 EXECUTING {action} - {symbol} ({tf})")
            print(f"   Strength: {strength:.0%}")
            
            # Show key analysis points
            analysis = signal_data.get('analysis', {})
            if analysis.get('patterns', {}).get('count', 0) > 0:
                patterns = analysis['patterns']['patterns'][:2]
                print(f"   🔥 {', '.join(patterns)}")
            
            # Calculate lot size
            lot_size = self._calculate_lot_size(symbol)
            
            result = self.trader.place_order({
                'symbol': symbol,
                'action': action,
                'strength': strength,
                'lot_size': lot_size  # Pass calculated lot size
            })
            
            if result['success']:
                self.trades_today += 1
                
                print(f"✅ SUCCESS! Ticket: #{result.get('ticket')}")
                print(f"   Entry: {result.get('price'):.5f}")
                print(f"   SL: {result.get('sl'):.5f} | TP: {result.get('tp'):.5f}")
                print(f"   Lot: {lot_size}")
                print(f"   Trades: {self.trades_today}/{self.max_daily_trades}")
                print(f"{'='*60}")
                
                return True
            else:
                print(f"❌ FAILED: {result.get('error', 'Unknown')}")
                print(f"{'='*60}")
                return False
                
        except Exception as e:
            print(f"❌ Execute error: {e}")
            return False
    
    def _calculate_lot_size(self, symbol: str) -> float:
        """Calculate dynamic lot size based on balance and risk"""
        
        # If dynamic sizing disabled, use fixed lot
        if not self.dynamic_lot_sizing:
            return self.config['current']['lot']
        
        try:
            account = mt5.account_info()
            if not account:
                return self.config['current']['lot']
            
            # Use starting balance for consistency
            balance = self.starting_balance
            
            # Calculate risk amount
            risk_amount = balance * (self.risk_percent / 100)
            
            # Get symbol info
            symbol_info = mt5.symbol_info(symbol)
            if not symbol_info:
                return self.config['current']['lot']
            
            # Estimate SL distance in USD
            # For Gold: typically $8-15 SL
            # For Forex: calculate based on pip value
            
            if 'XAU' in symbol or 'GOLD' in symbol:
                sl_distance_usd = 10.0  # Average $10 SL for gold
            elif 'BTC' in symbol:
                sl_distance_usd = 500.0  # Bitcoin
            else:
                # Forex - estimate
                sl_distance_usd = 20.0  # Approximate for forex
            
            # Calculate lot size: risk_amount / sl_distance
            calculated_lot = risk_amount / sl_distance_usd
            
            # Round to valid lot size
            calculated_lot = round(calculated_lot, 2)
            
            # Ensure within limits
            min_lot = symbol_info.volume_min
            max_lot = min(symbol_info.volume_max, 0.1)  # Cap at 0.1 for safety
            
            calculated_lot = max(min_lot, min(calculated_lot, max_lot))
            
            return calculated_lot
            
        except Exception as e:
            print(f"Lot calculation error: {e}")
            return self.config['current']['lot']
    
    def _run_cycle(self) -> None:
        """Standard trading cycle (single symbol)"""
        try:
            # Manage positions
            self.trader.manage_open_positions()
            
            # Check limits
            current_positions = self._get_current_positions()
            total_open = len(current_positions)
            
            if total_open >= self.max_total_positions:
                print(f"⚠️ Max total positions reached ({total_open}/{self.max_total_positions})")
                return
            
            symbol_positions = len([p for p in current_positions if p.symbol == self.config['current']['symbol']])
            
            if symbol_positions >= self.max_positions_per_symbol:
                print(f"⚠️ Max positions for {self.config['current']['symbol']} ({symbol_positions}/{self.max_positions_per_symbol})")
                return
            
            if self.trades_today >= self.max_daily_trades:
                return
            
            # Get data
            df = self._get_market_data()
            if df.empty:
                return
            
            # Analyze
            analysis = self.analyzer.analyze_market(
                df,
                self.config['current']['symbol'],
                self.config
            )
            
            signal = analysis['overall']['signal']
            strength = analysis['overall']['strength']
            
            # Log
            timestamp = datetime.now().strftime('%H:%M:%S')
            print(f"\n[{timestamp}] {signal} ({strength:.0%}) | Positions: {total_open}/{self.max_total_positions}")
            
            # Execute
            if self._should_trade() and signal != 'WAIT':
                self._execute_signal({
                    'symbol': self.config['current']['symbol'],
                    'timeframe': self.config['current']['timeframe'],
                    'signal': signal,
                    'strength': strength,
                    'analysis': analysis
                })
                
        except Exception as e:
            print(f"❌ Cycle error: {e}")
    
    def _get_current_positions(self) -> List:
        """Get all current bot positions"""
        positions = mt5.positions_get()
        if not positions:
            return []
        
        # Filter only our bot's positions
        return [p for p in positions if p.magic == 234000]
    
    def _should_trade(self) -> bool:
        """Check if trading is allowed"""
        if not self.config.get('current', {}).get('auto_trade', False):
            return False
        
        account = mt5.account_info()
        if account and account.balance < 5:
            return False
        
        if self.config.get('current', {}).get('trade_always_on', True):
            return True
        
        now = datetime.now()
        return 1 <= now.hour < 23
    
    def _get_market_data(self) -> pd.DataFrame:
        """Get market data for current symbol"""
        return self._get_market_data_for(
            self.config['current']['symbol'],
            self.config['current']['timeframe']
        )
    
    def _get_market_data_for(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """Get market data for specific symbol/timeframe"""
        try:
            tf_map = {
                'M1': mt5.TIMEFRAME_M1,
                'M5': mt5.TIMEFRAME_M5,
                'M15': mt5.TIMEFRAME_M15,
                'M30': mt5.TIMEFRAME_M30,
                'H1': mt5.TIMEFRAME_H1,
                'H4': mt5.TIMEFRAME_H4,
                'D1': mt5.TIMEFRAME_D1
            }
            
            mt5_tf = tf_map.get(timeframe, mt5.TIMEFRAME_M5)
            candles = self.config['current']['candles']
            
            rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, candles)
            
            if rates is None or len(rates) == 0:
                return pd.DataFrame()
            
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            
            return df
            
        except Exception as e:
            return pd.DataFrame()
    
    def get_statistics(self) -> Dict:
        """Get bot statistics"""
        positions = self._get_current_positions()
        
        # Group by symbol
        symbol_counts = {}
        for p in positions:
            symbol_counts[p.symbol] = symbol_counts.get(p.symbol, 0) + 1
        
        total_profit = sum(p.profit for p in positions)
        
        return {
            'trades_today': self.trades_today,
            'max_daily_trades': self.max_daily_trades,
            'remaining_trades': self.max_daily_trades - self.trades_today,
            'open_positions': len(positions),
            'max_total_positions': self.max_total_positions,
            'positions_by_symbol': symbol_counts,
            'floating_pl': total_profit,
            'is_running': self.running,
            'trade_date': self.last_trade_date.strftime('%Y-%m-%d'),
            'starting_balance': self.starting_balance
        }