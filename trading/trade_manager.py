# trading/trade_manager.py - FIXED VERSION
from typing import Dict, Optional
import MetaTrader5 as mt5
from datetime import datetime
import pandas as pd
import numpy as np

class TradeManager:
    def __init__(self, config: Dict):
        self.config = config
        self.positions = {}
        
    def place_order(self, signal: Dict) -> Dict:
        """Place order with proper SL/TP calculation"""
        try:
            symbol = signal['symbol']
            action = signal['action']
            
            # Use custom lot size if provided, otherwise use config
            lot_size = signal.get('lot_size', self.config['current']['lot'])
            
            if action not in ['BUY', 'SELL']:
                return {'success': False, 'error': 'Invalid action'}
            
            # Get symbol info
            symbol_info = mt5.symbol_info(symbol)
            if not symbol_info:
                return {'success': False, 'error': 'Symbol info not available'}
            
            # Get current price
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                return {'success': False, 'error': 'Could not get price'}
            
            # Calculate entry price
            price = tick.ask if action == 'BUY' else tick.bid
            
            # Get symbol parameters
            point = symbol_info.point
            digits = symbol_info.digits
            stops_level = symbol_info.trade_stops_level
            
            # Calculate ATR for dynamic SL/TP
            atr = self._calculate_atr(symbol)
            
            # For Gold (XAUUSD), ATR is typically 5-15
            # For Forex pairs, ATR is 0.0005-0.0020
            
            # Determine if this is Gold/Commodity or Forex
            if 'XAU' in symbol or 'GOLD' in symbol:
                # Gold - use dollar-based SL/TP
                sl_distance = max(atr * 1.5, 3.0)  # Min $3 SL
                tp_distance = max(atr * 2.0, 5.0)  # Min $5 TP
            else:
                # Forex - use pip-based SL/TP
                sl_pips = max(int(atr / point * 1.5), 20)  # Min 20 pips
                tp_pips = max(int(atr / point * 2.0), 40)  # Min 40 pips
                sl_distance = sl_pips * point
                tp_distance = tp_pips * point
            
            # Ensure minimum distance from broker
            min_distance = stops_level * point
            if min_distance > 0:
                sl_distance = max(sl_distance, min_distance * 2)
                tp_distance = max(tp_distance, min_distance * 2)
            
            # Calculate SL and TP
            if action == 'BUY':
                sl = round(price - sl_distance, digits)
                tp = round(price + tp_distance, digits)
            else:  # SELL
                sl = round(price + sl_distance, digits)
                tp = round(price - tp_distance, digits)
            
            # Validate SL/TP
            if action == 'BUY':
                if sl >= price or tp <= price:
                    return {'success': False, 'error': f'Invalid SL/TP: Price={price}, SL={sl}, TP={tp}'}
            else:  # SELL
                if sl <= price or tp >= price:
                    return {'success': False, 'error': f'Invalid SL/TP: Price={price}, SL={sl}, TP={tp}'}
            
            # Check if symbol allows trading
            if not symbol_info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL:
                return {'success': False, 'error': 'Trading not allowed for this symbol'}
            
            # Determine filling type
            filling_type = self._get_filling_type(symbol_info)
            
            # Prepare trade request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": lot_size,
                "type": mt5.ORDER_TYPE_BUY if action == 'BUY' else mt5.ORDER_TYPE_SELL,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": self.config['current']['slippage'],
                "magic": 234000,
                "comment": f"Bot {signal.get('strength', 0):.0%}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_type,
            }
            
            # Log the request for debugging
            print(f"\n📋 Order Request:")
            print(f"   Symbol: {symbol}")
            print(f"   Action: {action}")
            print(f"   Price: {price:.{digits}f}")
            print(f"   SL: {sl:.{digits}f} (distance: {abs(price-sl):.{digits}f})")
            print(f"   TP: {tp:.{digits}f} (distance: {abs(tp-price):.{digits}f})")
            print(f"   Lot: {lot_size}")
            
            # Send order
            result = mt5.order_send(request)
            
            if result is None:
                return {'success': False, 'error': 'order_send returned None'}
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                error_msg = f"Order failed: {result.comment} (code: {result.retcode})"
                
                # Provide helpful error messages
                if result.retcode == mt5.TRADE_RETCODE_INVALID_STOPS:
                    error_msg += f"\n   Hint: SL/TP too close. Min distance: {min_distance:.{digits}f}"
                elif result.retcode == mt5.TRADE_RETCODE_NO_MONEY:
                    error_msg += f"\n   Hint: Insufficient funds. Check margin requirements."
                elif result.retcode == mt5.TRADE_RETCODE_INVALID_PRICE:
                    error_msg += f"\n   Hint: Price changed. Try again."
                
                return {'success': False, 'error': error_msg}
            
            return {
                'success': True,
                'ticket': result.order,
                'price': price,
                'sl': sl,
                'tp': tp,
                'volume': lot_size
            }
            
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            return {'success': False, 'error': f'{str(e)}\n{error_detail}'}
    
    def _get_filling_type(self, symbol_info) -> int:
        """Determine the correct filling type for the symbol"""
        filling_modes = symbol_info.filling_mode
        
        # Check available filling modes
        if filling_modes & 2:  # FOK (Fill or Kill)
            return mt5.ORDER_FILLING_FOK
        elif filling_modes & 1:  # IOC (Immediate or Cancel)
            return mt5.ORDER_FILLING_IOC
        else:  # Return (Market execution)
            return mt5.ORDER_FILLING_RETURN
    
    def _calculate_atr(self, symbol: str, period: int = 14) -> float:
        """Calculate ATR for SL/TP sizing"""
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, period + 1)
        
        if rates is None or len(rates) < period:
            # Default ATR based on symbol
            if 'XAU' in symbol or 'GOLD' in symbol:
                return 8.0  # Gold default ~$8 ATR
            elif 'BTC' in symbol:
                return 500.0  # Bitcoin
            else:
                return 0.0010  # Forex default
        
        df = pd.DataFrame(rates)
        
        # Calculate True Range
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean().iloc[-1]
        
        # Ensure minimum ATR
        if pd.isna(atr) or atr == 0:
            if 'XAU' in symbol or 'GOLD' in symbol:
                return 8.0
            else:
                return 0.0010
        
        return atr
    
    def modify_position(self, ticket: int, new_sl: Optional[float] = None, new_tp: Optional[float] = None) -> bool:
        """Modify existing position's SL/TP"""
        try:
            position = mt5.positions_get(ticket=ticket)
            if not position:
                return False
            
            pos = position[0]
            symbol_info = mt5.symbol_info(pos.symbol)
            
            # Use existing values if not provided
            sl = new_sl if new_sl is not None else pos.sl
            tp = new_tp if new_tp is not None else pos.tp
            
            # Round to symbol digits
            if sl:
                sl = round(sl, symbol_info.digits)
            if tp:
                tp = round(tp, symbol_info.digits)
            
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol": pos.symbol,
                "sl": sl,
                "tp": tp
            }
            
            result = mt5.order_send(request)
            return result.retcode == mt5.TRADE_RETCODE_DONE
            
        except Exception as e:
            print(f"Error modifying position: {e}")
            return False
    
    def close_position(self, ticket: int) -> bool:
        """Close specific position"""
        try:
            position = mt5.positions_get(ticket=ticket)
            if not position:
                return False
            
            pos = position[0]
            symbol_info = mt5.symbol_info(pos.symbol)
            tick = mt5.symbol_info_tick(pos.symbol)
            
            if not tick:
                return False
            
            # Determine close price
            close_price = tick.bid if pos.type == 0 else tick.ask
            
            # Determine filling type
            filling_type = self._get_filling_type(symbol_info)
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": ticket,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
                "price": close_price,
                "deviation": self.config['current']['slippage'],
                "magic": 234000,
                "comment": "Bot Close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_type,
            }
            
            result = mt5.order_send(request)
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"✅ Position {ticket} closed at {close_price}")
                return True
            else:
                print(f"❌ Close failed: {result.comment}")
                return False
            
        except Exception as e:
            print(f"Error closing position: {e}")
            return False
    
    def manage_open_positions(self) -> None:
        """Manage all open positions - AUTO CLOSE, BEP, TRAILING"""
        try:
            positions = mt5.positions_get()
            if not positions:
                return
            
            for position in positions:
                # Skip positions not from our bot
                if position.magic != 234000:
                    continue
                
                # === 1. AUTO-CLOSE PROFIT (PRIORITY PERTAMA) ===
                if self.config['current']['auto_close_profit']:
                    target = self.config['current']['auto_close_target']
                    
                    if position.profit >= target:
                        timestamp = datetime.now().strftime('%H:%M:%S')
                        print(f"\n[{timestamp}] 💰 AUTO-CLOSE PROFIT TARGET HIT!")
                        print(f"   {position.symbol} Ticket #{position.ticket}")
                        print(f"   Profit: ${position.profit:.2f} (Target: ${target:.2f})")
                        
                        if self.close_position(position.ticket):
                            print(f"   ✅ Position closed successfully!")
                        else:
                            print(f"   ❌ Failed to close position")
                        
                        continue  # Skip other management for this position
                
                # === 2. BREAKEVEN ===
                if self.config['current']['bep']:
                    self._check_breakeven(position)
                
                # === 3. TRAILING STOP ===
                if self.config['current']['stpp_trailing']:
                    self._update_trailing_stop(position)
                    
        except Exception as e:
            print(f"Error managing positions: {e}")
    
    def _check_breakeven(self, position) -> None:
        """Move SL to breakeven when profit threshold reached"""
        try:
            min_profit = self.config['current']['bep_min_profit']
            
            # Check if profit meets threshold
            if position.profit < min_profit:
                return
            
            symbol_info = mt5.symbol_info(position.symbol)
            spread = (symbol_info.ask - symbol_info.bid)
            
            # Calculate breakeven level (entry + spread)
            if position.type == 0:  # BUY
                bep_level = position.price_open + spread
                # Only move SL up
                if position.sl < bep_level:
                    print(f"🔒 Moving to BEP: {position.symbol} @ {bep_level:.{symbol_info.digits}f}")
                    self.modify_position(position.ticket, new_sl=bep_level)
            else:  # SELL
                bep_level = position.price_open - spread
                # Only move SL down
                if position.sl > bep_level or position.sl == 0:
                    print(f"🔒 Moving to BEP: {position.symbol} @ {bep_level:.{symbol_info.digits}f}")
                    self.modify_position(position.ticket, new_sl=bep_level)
                    
        except Exception as e:
            print(f"BEP error: {e}")
    
    def _update_trailing_stop(self, position) -> None:
        """Update trailing stop based on profit"""
        try:
            step_init = self.config['current']['step_lock_init']
            step_size = self.config['current']['step_step']
            
            # Check if profit meets initial threshold
            if position.profit < step_init:
                return
            
            symbol_info = mt5.symbol_info(position.symbol)
            point = symbol_info.point
            
            # Calculate how many steps passed
            steps_passed = int((position.profit - step_init) / step_size)
            
            if steps_passed < 1:
                return
            
            # Calculate new SL level
            new_sl_distance = step_init + (steps_passed * step_size)
            
            # Convert USD to price distance (approximate)
            # For Gold: $1 ≈ 1 point, For Forex: need to calculate
            if 'XAU' in position.symbol or 'GOLD' in position.symbol:
                price_distance = new_sl_distance  # $1 = 1 point for gold
            else:
                # For forex, estimate based on pip value
                price_distance = new_sl_distance * point * 10
            
            if position.type == 0:  # BUY
                new_sl = position.price_open + price_distance
                # Only move SL up
                if new_sl > position.sl:
                    print(f"📈 Trailing SL: {position.symbol} @ {new_sl:.{symbol_info.digits}f}")
                    self.modify_position(position.ticket, new_sl=new_sl)
            else:  # SELL
                new_sl = position.price_open - price_distance
                # Only move SL down
                if new_sl < position.sl or position.sl == 0:
                    print(f"📉 Trailing SL: {position.symbol} @ {new_sl:.{symbol_info.digits}f}")
                    self.modify_position(position.ticket, new_sl=new_sl)
                    
        except Exception as e:
            print(f"Trailing stop error: {e}")