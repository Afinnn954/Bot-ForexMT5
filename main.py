import os
import json
import time
import threading
import MetaTrader5 as mt5
from datetime import datetime
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import requests
from google import genai
from google.genai.errors import APIError
from google.genai.types import GenerationConfig
from analyzers.market_analyzer import MarketAnalyzer
from trading.trade_manager import TradeManager
from bot.bot_manager import TradingBot


# --------------------------
# 1. LOAD KONFIG & ENV
# --------------------------
def load_environment():
    """
    Load .env and return a dict with multiple key formats to avoid
    mismatches between UPPER and snake_case usages in the code.
    """
    load_dotenv()  # load .env into os.environ

    # Basic presence debug (masked) - will not print the full key
    raw_key = os.getenv("GEMINI_API_KEY") or os.getenv("gemini_api_key")
    if raw_key:
        masked = raw_key[:4] + "..." + raw_key[-4:] if len(raw_key) > 8 else "****"
        print(f"\n✅ GEMINI_API_KEY found in environment (masked): {masked}")
    else:
        print("\n⚠️ GEMINI_API_KEY not found in environment variables")

    env = {
        # UPPER keys (if other parts of code expect these)
        "MT5_LOGIN": os.getenv("MT5_LOGIN"),
        "MT5_PASSWORD": os.getenv("MT5_PASSWORD"),
        "MT5_SERVER": os.getenv("MT5_SERVER"),
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY"),
        "NEWS_API_KEY": os.getenv("NEWS_API_KEY"),
        "TRADING_ECONOMICS_KEY": os.getenv("TRADING_ECONOMICS_KEY", "guest:guest"),

        # snake_case keys (common in this project)
        "mt5_login": int(os.getenv("MT5_LOGIN")) if os.getenv("MT5_LOGIN") and os.getenv("MT5_LOGIN").isdigit() else 0,
        "mt5_password": os.getenv("MT5_PASSWORD", ""),
        "mt5_server": os.getenv("MT5_SERVER", ""),
        "gemini_api_key": os.getenv("GEMINI_API_KEY"),
        "news_api_key": os.getenv("NEWS_API_KEY", ""),
        "trading_economics_key": os.getenv("TRADING_ECONOMICS_KEY", "guest:guest"),
    }
    return env


def load_config(config_path: str = "config.json") -> dict:
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: config.json tidak ditemukan!")
        return None


def save_config(config: dict, config_path: str = "config.json") -> None:
    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"✅ Konfigurasi disimpan ke {config_path}")
    except Exception as e:
        print(f"❌ Gagal menyimpan konfigurasi: {str(e)}")

def init_gemini() -> genai.Client:
    """Inisialisasi Gemini API dengan model terbaru"""
    api_key = env.get("GEMINI_API_KEY")
    
    if not api_key or api_key == "":
        print("\n⚠️ GEMINI_API_KEY tidak ditemukan di .env!")
        return None
        
    try:
        # 1. Initialize Gemini with the API Key
        client = genai.Client(api_key=api_key) # Pass key to Client for a modern approach
        
        # 2. Test connection (by using a model on the client)
        response = client.models.generate_content(
            model='gemini-2.5-flash', # Specify the model here
            contents="test connection"
        )
        
        if response.text: # Check if the content was generated successfully
            print("\n✅ Gemini AI siap digunakan!")
            return client # Return the client instancel
            
    except Exception as e:
        print(f"\n❌ Gagal inisialisasi Gemini: {e}")
        print("ℹ️ Bot akan berjalan tanpa analisis AI")
        print("💡 Pastikan:")
        print("1. API key valid dan aktif")
        print("2. Package google-generativeai terinstall versi terbaru")
        print("3. Koneksi internet stabil")
    return None

# Inisialisasi global (akan diinisialisasi di main())
gemini_client = None

# --------------------------
# 2. KONEKSI & UTIL MT5
# --------------------------
env = load_environment()
mt5_terhubung = False


def get_available_symbols() -> list:
    """Get list of available symbols with variations"""
    symbols = []
    if mt5_terhubung:
        # Get all symbols
        all_symbols = mt5.symbols_get()
        if all_symbols:
            for symbol_info in all_symbols:
                name = symbol_info.name
                # Check for common forex pairs and variations
                if any(pair in name for pair in ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'XAUUSD', 'BTCUSD']):
                    symbols.append(name)
    return symbols

def init_mt5() -> bool:
    global mt5_terhubung
    
    # Shutdown existing connection if any
    if mt5.initialize():
        mt5.shutdown()
    
    # Try multiple MT5 installation paths
    mt5_paths = [
        "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
        "C:\\Program Files (x86)\\MetaTrader 5\\terminal64.exe",
        None  # Let MT5 find the path automatically
    ]
    
    for path in mt5_paths:
        try:
            if mt5.initialize(
                login=env["mt5_login"],
                password=env["mt5_password"],
                server=env["mt5_server"],
                path=path
            ):
                # Test connection by getting account info
                akun = mt5.account_info()
                if akun:
                    print(f"\n✅ Terhubung ke MT5 | Akun: {akun.login} | Saldo: {akun.balance} {akun.currency}")
                    mt5_terhubung = True
                    
                    # Get and subscribe to available symbols
                    all_symbols = mt5.symbols_get()
                    if all_symbols:
                        common_prefixes = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "BTCUSD"]
                        found_symbols = []
                        
                        # Find available variants
                        for prefix in common_prefixes:
                            for sym in all_symbols:
                                if sym.name.upper().startswith(prefix):
                                    if mt5.symbol_select(sym.name, True):
                                        print(f"✅ Subscribe {sym.name}")
                                        found_symbols.append(sym.name)
                                    break  # Take first matching variant
                        
                        if found_symbols:
                            print(f"\nℹ️ Subscribed to: {', '.join(found_symbols)}")
                        else:
                            print("\n⚠️ No common symbols found. Please select symbols manually.")
                    
                    return True
        except Exception as e:
            print(f"⚠️ Error path {path}: {str(e)}")
            continue
    
    print(f"\n❌ Gagal terhubung MT5 | Error: {mt5.last_error()}")
    mt5_terhubung = False
    return False


def map_timeframe(timeframe_str: str) -> int:
    mapping = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1
    }
    return mapping.get(timeframe_str, mt5.TIMEFRAME_M30)


def select_symbol(symbol_baru: str) -> bool:
    """Select a symbol in MT5 with fallback variations"""
    # Get available symbols
    all_symbols = mt5.symbols_get()
    available_symbols = []
    if all_symbols:
        for symbol_info in all_symbols:
            available_symbols.append(symbol_info.name)
    
    # Get uppercase input but preserve original for display
    symbol_upper = symbol_baru.upper()
    
    # Try exact match first (case insensitive)
    for available in available_symbols:
        if available.upper() == symbol_upper:
            if mt5.symbol_select(available, True):
                print(f"✅ Symbol {available} selected")
                return True
    
    # Try variations (case insensitive)
    variations = [
        symbol_upper,
        f"{symbol_upper}m",    # Some brokers use 'm' suffix for micro
        f"{symbol_upper}-m",   # Dash variation
        f"{symbol_upper}.a",   # Some use .a suffix
        f"{symbol_upper}-a",   # Dash variation
        f"{symbol_upper}_m",   # Underscore variation
        symbol_upper.replace('XAU', 'GOLD'),  # Special case for gold
        symbol_upper.replace('GOLD', 'XAU')   # Both directions
    ]
    
    # Try each variation with case-insensitive matching
    for variant in variations:
        for available in available_symbols:
            if available.upper() == variant:
                if mt5.symbol_select(available, True):
                    print(f"✅ Found matching symbol: {available}")
                    return True
    
    # If no exact match, look for similar symbols
    print(f"❌ Symbol {symbol_baru} not found")
    
    # First show exact matches ignoring case
    exact_matches = [s for s in available_symbols if s.upper() == symbol_upper]
    if exact_matches:
        print("\nExact matches (different case):")
        for sym in exact_matches:
            print(f"- {sym}")
    
    # Then show similar symbols
    print("\nSimilar symbols:")
    similar_symbols = [s for s in available_symbols if any(
        var in s.upper() for var in variations
    ) and s not in exact_matches]
    
    if similar_symbols:
        # Show gold-related symbols first if searching for gold
        if 'GOLD' in symbol_upper or 'XAU' in symbol_upper:
            gold_symbols = [s for s in similar_symbols if 'GOLD' in s.upper() or 'XAU' in s.upper()]
            if gold_symbols:
                for sym in sorted(gold_symbols)[:5]:
                    print(f"- {sym}")
    
        # Then show other similar symbols
        other_symbols = [s for s in similar_symbols if s not in gold_symbols] if 'gold_symbols' in locals() else similar_symbols
        if other_symbols:
            print("\nOther similar symbols:")
            for sym in sorted(other_symbols)[:5]:
                print(f"- {sym}")
    else:
        print("No similar symbols found")
    
    # Get most common forex pairs for suggestions
    common_pairs = [s for s in available_symbols if any(
        pair in s for pair in ['EUR', 'USD', 'GBP', 'JPY', 'XAU', 'GOLD']
    )]
    
    if common_pairs:
        print("\nPopular trading symbols:")
        for sym in sorted(common_pairs)[:10]:
            print(f"- {sym}")
    
    return False

def ambil_candle(symbol: str, timeframe: str, jumlah: int) -> pd.DataFrame:
    if not mt5_terhubung:
        print("❌ MT5 belum terhubung!")
        return pd.DataFrame()
    
    # Ensure symbol is selected with enhanced selection
    if not select_symbol(symbol):
        return pd.DataFrame()

    # Try different methods to get data
    mt5_tf = map_timeframe(timeframe)
    
    # Method 1: copy_rates_from_pos
    data = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, jumlah)
    
    if data is None:
        # Method 2: copy_rates_range
        from_date = pd.Timestamp.now() - pd.Timedelta(days=5)
        to_date = pd.Timestamp.now()
        
        data = mt5.copy_rates_range(
            symbol,
            mt5_tf,
            from_date.timetuple(),
            to_date.timetuple()
        )
    
    if data is None:
        print(f"❌ Gagal mengambil candle | Error: {mt5.last_error()}")
        # Reinitialize MT5 connection
        if init_mt5():
            print("✅ Berhasil reconnect MT5")
            # Try one more time
            data = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, jumlah)
    
    if data is None:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df

def fetch_latest_news(api_key, symbol):
    """Mengambil berita terbaru yang relevan dengan simbol (misal: Gold/XAUUSD)"""
    if not api_key:
        return "No News API Key available."
        
    # Contoh URL untuk mencari berita tentang 'Gold' atau 'USD'
    url = f"https://newsapi.org/v2/everything?q={symbol}&sortBy=publishedAt&apiKey={api_key}&pageSize=5"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        data = response.json()
        
        if data['status'] == 'ok' and data['articles']:
            # Gabungkan judul dan deskripsi beberapa artikel menjadi satu string untuk dianalisis Gemini
            combined_text = "\n".join([f"- {a['title']}: {a['description']}" for a in data['articles']])
            return combined_text
        else:
            return f"No relevant news found for {symbol} today."
            
    except requests.RequestException as e:
        return f"News API Request Failed: {e}"
    
def analyze_with_gemini_advanced(client: genai.Client, analysis: dict, df: pd.DataFrame, symbol: str) -> dict:
    """
    Advanced Gemini AI analysis with structured output
    """
    if not client:
        return {"recommendation": "WAIT", "confidence": 0, "reason": "Gemini not available"}

    # Prepare comprehensive data for AI
    last_close = df['close'].iloc[-1]
    price_change_5 = ((df['close'].iloc[-1] / df['close'].iloc[-5]) - 1) * 100 if len(df) >= 5 else 0
    price_change_20 = ((df['close'].iloc[-1] / df['close'].iloc[-20]) - 1) * 100 if len(df) >= 20 else 0
    
    # Get technical summary
    tech = analysis['technical']
    news = analysis['news']
    calendar = analysis['calendar']
    
    high = df['high'].tail(10).max()
    low = df['low'].tail(10).min()
    
    # Construct detailed prompt
    system_prompt = """You are an expert Forex/Crypto trading AI analyst. 
    Analyze the provided market data and give a trading recommendation in JSON format.
    
    You MUST respond in this exact JSON format:
    {
      "recommendation": "BUY" or "SELL" or "WAIT",
      "confidence": 0-100,
      "entry_price": suggested entry price,
      "stop_loss": suggested SL price,
      "take_profit": suggested TP price,
      "risk_reward_ratio": calculated R:R,
      "key_factors": [list of 3-5 key factors influencing decision],
      "warnings": [list of risks or concerns],
      "timeframe": "short-term" or "medium-term" or "long-term"
    }
    
    Base your analysis on:
    1. Technical indicators and trends
    2. News sentiment
    3. Economic calendar events
    4. Risk management principles
    5. Current market conditions
    """
    
    market_data = f"""
=== MARKET ANALYSIS FOR {symbol} ===

PRICE DATA:
- Current Price: {last_close:.5f}
- 5-bar Change: {price_change_5:+.2f}%
- 20-bar Change: {price_change_20:+.2f}%
- 10-bar High: {high:.5f}
- 10-bar Low: {low:.5f}

TECHNICAL ANALYSIS:
- Signal: {tech['signal']}
- Bullish Signals: {tech['bullish']}
- Bearish Signals: {tech['bearish']}
- Confidence: {tech.get('confidence', 0):.1%}
- Key Indicators:
{chr(10).join(['  • ' + s for s in tech['signals'][:5]])}

NEWS SENTIMENT:
- Impact: {news['impact']}
- Sentiment Score: {news.get('sentiment_score', 0)}
- Recent Headlines:
{chr(10).join(['  • ' + h[:80] for h in news.get('headlines', [])[:3]])}

ECONOMIC CALENDAR:
- Impact Level: {calendar['impact']}
- High Impact Events: {calendar.get('high_impact_count', 0)}
- Upcoming Events:
{chr(10).join(['  • ' + e for e in calendar.get('events', [])[:3]])}

OVERALL ANALYSIS:
- Combined Signal: {analysis['overall']['signal']}
- Signal Strength: {analysis['overall']['strength']:.1%}
- Key Reasons:
{chr(10).join(['  • ' + r for r in analysis['overall']['reasons'][:5]])}

=== TASK ===
Based on this comprehensive analysis, provide your expert trading recommendation.
Consider risk management, current volatility, and all factors above.
"""

    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash-exp',
            contents=market_data,
            config={
                "system_instruction": system_prompt,
                "response_mime_type": "application/json",
                "temperature": 0.3,  # Lower temperature for more consistent output
            }
        )
        
        # Parse JSON response
        import json
        ai_analysis = json.loads(response.text)
        
        # Validate response
        required_keys = ['recommendation', 'confidence', 'key_factors']
        if all(key in ai_analysis for key in required_keys):
            return ai_analysis
        else:
            print("⚠️ AI response missing required fields")
            return {"recommendation": "WAIT", "confidence": 0, "reason": "Invalid AI response"}
            
    except json.JSONDecodeError as e:
        print(f"❌ AI JSON decode error: {e}")
        print(f"Raw response: {response.text[:200]}")
        return {"recommendation": "WAIT", "confidence": 0, "reason": "JSON decode failed"}
    except Exception as e:
        print(f"❌ Gemini AI Error: {e}")
        return {"recommendation": "WAIT", "confidence": 0, "reason": str(e)}
# --------------------------
# 3. TAMPILAN & INPUT MENU
# --------------------------
def get_account_summary() -> dict:
    """Get account summary including today's P&L"""
    if not mt5_terhubung:
        return None
        
    account = mt5.account_info()
    if not account:
        return None
    
    # Get today's deals for P&L calculation
    from_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    to_date = datetime.now()
    
    deals = mt5.history_deals_get(from_date, to_date)
    
    today_profit = 0
    today_loss = 0
    total_trades = 0
    
    if deals:
        for deal in deals:
            # Skip balance operations
            if deal.type in [0, 1]:  # Buy or Sell deals only
                if deal.profit != 0:  # Closing deals
                    total_trades += 1
                    if deal.profit > 0:
                        today_profit += deal.profit
                    else:
                        today_loss += abs(deal.profit)
    
    # Calculate percentages
    starting_balance = account.balance - (today_profit - today_loss)
    profit_percent = (today_profit / starting_balance * 100) if starting_balance > 0 else 0
    loss_percent = (today_loss / starting_balance * 100) if starting_balance > 0 else 0
    
    # Get open positions
    positions = mt5.positions_get()
    open_positions = len(positions) if positions else 0
    floating_pl = sum(pos.profit for pos in positions) if positions else 0
    
    return {
        'balance': account.balance,
        'equity': account.equity,
        'margin': account.margin,
        'free_margin': account.margin_free,
        'currency': account.currency,
        'leverage': account.leverage,
        'today_profit': today_profit,
        'today_loss': today_loss,
        'today_net': today_profit - today_loss,
        'profit_percent': profit_percent,
        'loss_percent': loss_percent,
        'total_trades': total_trades,
        'open_positions': open_positions,
        'floating_pl': floating_pl
    }
    
# Letakkan ini di bagian atas file main.py, di bawah bagian import
last_backtest_result = None

# Gantikan fungsi cetak_menu() yang lama dengan yang ini
def cetak_menu(config: dict) -> None:
    global last_backtest_result
    current = config["current"]
    options = config["options"]
    
    # Helper untuk format ON/OFF
    def status(value):
        return "ON" if value else "OFF"

    # Helper untuk format baris menu
    def format_line(num, text, current_val, hint=""):
        # Menghapus 'Toggle' dan 'Set' untuk deskripsi yang lebih pendek
        text = text.replace("Toggle ", "").replace("Set ", "")
        
        # Membuat string utama
        line = f"{num:>2}) {text:<25}"
        
        # Menambahkan nilai saat ini
        current_str = f"(current: {current_val})"
        line = f"{line}{current_str:<25}"
        
        # Menambahkan hint jika ada
        if hint:
            line += f" {hint}"
        print(line)

    print("\n" + "="*90)

    # --- HEADER: Tampilkan hasil backtest terakhir atau status akun ---
    if last_backtest_result:
        print(last_backtest_result)
        last_backtest_result = None  # Reset agar hanya tampil sekali
    else:
        summary = get_account_summary()
        if summary:
            pl_sign = "+" if summary['today_net'] >= 0 else "-"
            print(f"💰 Balance: ${summary['balance']:.2f} | Equity: ${summary['equity']:.2f} | Today's P/L: {pl_sign}${abs(summary['today_net']):.2f} | Open: {summary['open_positions']}")

    print("="*90)
    print("Menu:")

    # --- MENU UTAMA ---
    print(" 1) Analyze now")
    format_line(2, "Change SYMBOL", current['symbol'], f"available: {', '.join(get_available_symbols()[:5])}...")
    format_line(3, "Change TIMEFRAME", current['timeframe'], f"options: {', '.join(options['timeframes'])}")
    format_line(4, "Change CANDLES", current['candles'], "e.g. 50 / 100 / 200")
    format_line(5, "Switch ACCOUNT", current['account'], f"options: {', '.join(options['accounts'])}")
    format_line(6, "Change TRADE MODE", current['trade_mode'], f"options: {', '.join(options['trade_modes'])}")
    print(" 7) Launch external TRAINER window (every 10s, bars=800)")
    format_line(8, "Toggle AUTO-TRADE", status(current['auto_trade']))
    format_line(9, "Set AUTO lot", current['lot'])
    format_line(10, "Set AUTO slippage (dev)", current['slippage'])
    format_line(11, "Toggle AUTO-CLOSE profit", status(current['auto_close_profit']))
    format_line(12, "Set AUTO-CLOSE target USD", current['auto_close_target'])
    format_line(13, "Toggle AUTO-ANALYZE", status(current['auto_analyze']))
    format_line(14, "Set AUTO-ANALYZE interval minutes", current['auto_analyze_interval'])
    format_line(15, "Toggle BEP", status(current['bep']))
    format_line(16, "Set BEP min profit USD", current['bep_min_profit'])
    format_line(17, "Set BEP spread multiplier", current['bep_spread_multiplier'])
    format_line(18, "Toggle STEP TRAILING", status(current['stpp_trailing']))
    format_line(19, "Set STEP lock init USD", current['step_lock_init'])
    format_line(20, "Set STEP step USD", current['step_step'])
    print(" 0) Quit")

    # --- KELOMPOK MENU LAINNYA ---
    print("\n-- Price Trigger --")
    print("21) Set ONE-SHOT price trigger (symbol, side, price, lot, SL, TP, int-match)")
    print("22) Cancel price trigger")
    format_line(23, "Set ENTRY match decimals", current['entry_decimals'], "e.g. None/0/1/2")

    print("\n-- Backtest --")
    print("24) Backtest (custom range) -> CSV")
    print("25) Backtest 1 minggu (last 7d)")
    print("26) Backtest 2 minggu (last 14d)")
    print("27) Backtest 1 bulan (last 30d)")
    print("28) Backtest 2 bulan (last 60d)")


    print("\n-- General --")
    format_line(29, "Toggle TRADE ALWAYS ON", status(current['trade_always_on']))
    print("30) Change mode (SCALPING/AGGRESSIVE/MODERATE/CONSERVATIVE)")
    print("31) Multi-position setup (RAPID FIRE mode)")  # TAMBAH INI
    
    print("\n-- Controls --")
    print("99) START TRADING")
    print("-" * 90)


def pilih_menu() -> int:
    pilihan = input("Select: ").strip()
    
    # Handle empty input
    if not pilihan:
        print("❌ Silakan masukkan pilihan menu!")
        return -1
        
    try:
        nilai = int(pilihan)
        
        # Validate menu option range
        valid_options = list(range(0, 32)) + [99]  # 0-29 plus 99
        if nilai not in valid_options:
            print(f"❌ Pilihan {nilai} tidak tersedia dalam menu!")
            return -1
            
        return nilai
        
    except ValueError:
        # Handle non-numeric input more gracefully
        print(f"❌ '{pilihan}' bukan pilihan yang valid! Masukkan nomor menu (0-30 atau 99)")
        return -1


# --------------------------
# 4. FUNGSI MENU (SESUI AI FOTO)
# --------------------------
def menu_1_analyze_now(config: dict, gemini_client: genai.Client) -> None:
    """Analyze now - AGGRESSIVE MODE"""
    print(f"\n🔍 Analyzing {config['current']['symbol']} ({config['current']['timeframe']})...")
    print(f"Mode: {config['current']['trade_mode']} | Threshold: {config['current']['signal_threshold']}")
    
    # 1. Get market data
    df = ambil_candle(
        symbol=config["current"]["symbol"],
        timeframe=config["current"]["timeframe"],
        jumlah=config["current"]["candles"]
    )
    if df.empty: 
        print("❌ Cannot get candle data")
        return
    
    # 2. Initialize analyzer
    analyzer = MarketAnalyzer(
        news_api_key=env.get('news_api_key'),
        te_key=env.get('trading_economics_key')
    )
    
    # 3. Full analysis with config
    analysis = analyzer.analyze_market(df, config['current']['symbol'], config)
    
    # 4. Display results
    print("\n" + "="*80)
    print(f"📊 MARKET ANALYSIS - {config['current']['trade_mode']} MODE")
    print("="*80)
    
    # Technical
    print("\n🔧 TECHNICAL:")
    tech = analysis['technical']
    print(f"Signal: {tech['signal']} | Bullish: {tech['bullish']} | Bearish: {tech['bearish']}")
    for sig in tech['signals'][:5]:
        print(f"  • {sig}")
    
    # Patterns
    if analysis.get('patterns', {}).get('count', 0) > 0:
        print("\n📊 CANDLESTICK PATTERNS:")
        for pattern in analysis['patterns']['patterns']:
            print(f"  🔥 {pattern}")
    
    # Breakouts
    if analysis.get('breakout', {}).get('count', 0) > 0:
        print("\n💥 BREAKOUTS:")
        for bo in analysis['breakout']['breakouts']:
            print(f"  🚀 {bo}")
    
    # Scalping
    if config['current'].get('enable_scalping', True):
        scalp = analysis.get('scalping', {})
        if scalp.get('score', 0) != 0:
            print(f"\n⚡ SCALPING: Score {scalp['score']}")
            for sig in scalp.get('signals', []):
                print(f"  • {sig}")
    
    # AI Analysis (Optional - fast version)
    if gemini_client and config['current']['trade_mode'] != 'SCALPING':
        print("\n🤖 AI QUICK ANALYSIS:")
        try:
            quick_prompt = f"""
Analyze {config['current']['symbol']}:
- Technical: {tech['signal']} ({tech['bullish']} bull, {tech['bearish']} bear)
- Patterns: {analysis.get('patterns', {}).get('patterns', [])}
- Price: {df['close'].iloc[-1]:.5f}

Give ONE sentence: BUY/SELL/WAIT and why.
"""
            response = gemini_client.models.generate_content(
                model='gemini-2.0-flash-exp',
                contents=quick_prompt
            )
            if response.text:
                print(f"  {response.text[:150]}")
        except:
            pass
    
    # Overall
    print("\n🎯 FINAL DECISION:")
    overall = analysis['overall']
    print(f"Signal: {overall['signal']} | Strength: {overall['strength']:.1%}")
    for reason in overall['reasons'][:5]:
        print(f"  {reason}")
    
    # Market status
    symbol_info = mt5.symbol_info(config['current']['symbol'])
    if symbol_info:
        print(f"\n💱 Market: Bid {symbol_info.bid:.5f} | Ask {symbol_info.ask:.5f}")
    
    print("="*80)

def menu_2_change_symbol(config: dict) -> dict:
    # Show current symbol info first
    current_symbol = config["current"]["symbol"]
    symbol_info = mt5.symbol_info(current_symbol)
    
    print("\nℹ️ Informasi Symbol Saat Ini:")
    if symbol_info:
        print(f"Symbol: {current_symbol}")
        print(f"Bid: {symbol_info.bid:.5f}")
        print(f"Ask: {symbol_info.ask:.5f}")
        print(f"Spread: {(symbol_info.ask - symbol_info.bid):.5f}")
        print(f"Digit: {symbol_info.digits}")
        print(f"Point: {symbol_info.point:.5f}")
    else:
        print(f"⚠️ Tidak dapat mengambil info untuk {current_symbol}")
    
    # Get common trading symbols
    all_symbols = mt5.symbols_get()
    if all_symbols:
        common_symbols = ['XAU', 'GOLD', 'EUR', 'GBP', 'JPY']
        popular = [s.name for s in all_symbols if any(pair in s.name for pair in common_symbols)]
        if popular:
            print("\nPopular symbols:")
            for sym in sorted(popular)[:5]:
                sym_info = mt5.symbol_info(sym)
                if sym_info:
                    print(f"- {sym} (Bid: {sym_info.bid:.5f} | Ask: {sym_info.ask:.5f})")
    
    # Get user input
    new_symbol = input(f"\nMasukkan symbol baru (e.g., EURUSD, XAUUSD, XAUUSDm): ").strip()
    
    # Try to select the symbol
    if select_symbol(new_symbol):
        config["current"]["symbol"] = new_symbol
        save_config(config)
        
        # Show new symbol info
        new_info = mt5.symbol_info(new_symbol)
        if new_info:
            print(f"\n✅ Symbol baru {new_symbol}:")
            print(f"Bid: {new_info.bid:.5f}")
            print(f"Ask: {new_info.ask:.5f}")
            print(f"Spread: {(new_info.ask - new_info.bid):.5f}")
            
    return config


def menu_3_change_timeframe(config: dict) -> dict:
    new_tf = input(f"\nMasukkan timeframe baru (Opsi: {', '.join(config['options']['timeframes'])}): ").strip().upper()
    if new_tf in config["options"]["timeframes"]:
        config["current"]["timeframe"] = new_tf
        save_config(config)
        print(f"✅ Timeframe diubah menjadi: {new_tf}")
    else:
        print(f"❌ Timeframe {new_tf} tidak tersedia!")
    return config


def menu_4_change_candles(config: dict) -> dict:
    try:
        new_count = int(input("\nMasukkan jumlah candle (contoh: 50, 100): "))
        if new_count > 0:
            config["current"]["candles"] = new_count
            save_config(config)
            print(f"✅ Jumlah candle diatur menjadi: {new_count}")
        else:
            print("❌ Jumlah candle harus positif!")
    except ValueError:
        print("❌ Input harus angka!")
    return config


def menu_5_switch_account(config: dict) -> dict:
    new_acc = input(f"\nMasukkan tipe akun (Opsi: {', '.join(config['options']['accounts'])}): ").strip().upper()
    if new_acc in config["options"]["accounts"]:
        config["current"]["account"] = new_acc
        save_config(config)
        print(f"✅ Akun diubah menjadi: {new_acc}")
    else:
        print(f"❌ Akun {new_acc} tidak tersedia!")
    return config


def menu_6_change_trade_mode(config: dict) -> dict:
    new_mode = input(f"\nMasukkan mode trading (Opsi: {', '.join(config['options']['trade_modes'])}): ").strip().upper()
    if new_mode in config["options"]["trade_modes"]:
        config["current"]["trade_mode"] = new_mode
        save_config(config)
        print(f"✅ Mode Trading diubah menjadi: {new_mode}")
    else:
        print(f"❌ Mode Trading {new_mode} tidak tersedia!")
    return config


def menu_7_launch_trainer(config: dict) -> None:
    """Launch training visualization window"""
    print("\n📚 Launching Trainer Mode...")
    
    try:
        import matplotlib.pyplot as plt
        from matplotlib.animation import FuncAnimation
        import matplotlib.dates as mdates
        
        # Create figure and axis
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 8))
        fig.suptitle(f'Trading Trainer - {config["current"]["symbol"]} ({config["current"]["timeframe"]})')
        
        def update_chart(frame):
            # Get latest data
            df = ambil_candle(
                symbol=config["current"]["symbol"],
                timeframe=config["current"]["timeframe"],
                jumlah=config["current"]["candles"]
            )
            
            if df.empty:
                return
            
            # Clear axes
            ax1.clear()
            ax2.clear()
            ax3.clear()
            
            # Plot 1: Price and Moving Averages
            ax1.plot(df['time'], df['close'], label='Close', color='blue', linewidth=1)
            
            # Add SMA
            df['SMA_20'] = df['close'].rolling(window=20).mean()
            df['SMA_50'] = df['close'].rolling(window=50).mean()
            ax1.plot(df['time'], df['SMA_20'], label='SMA 20', color='orange', alpha=0.7)
            ax1.plot(df['time'], df['SMA_50'], label='SMA 50', color='red', alpha=0.7)
            
            ax1.set_title('Price Action & Moving Averages')
            ax1.legend(loc='upper left')
            ax1.grid(True, alpha=0.3)
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            
            # Plot 2: Volume
            colors = ['g' if df['close'].iloc[i] > df['open'].iloc[i] else 'r' 
                     for i in range(len(df))]
            ax2.bar(df['time'], df['tick_volume'], color=colors, alpha=0.5)
            ax2.set_title('Volume')
            ax2.grid(True, alpha=0.3)
            
            # Plot 3: RSI
            # Calculate RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))
            
            ax3.plot(df['time'], df['RSI'], label='RSI', color='purple')
            ax3.axhline(y=70, color='r', linestyle='--', alpha=0.5, label='Overbought')
            ax3.axhline(y=30, color='g', linestyle='--', alpha=0.5, label='Oversold')
            ax3.fill_between(df['time'], 30, 70, alpha=0.1)
            ax3.set_title('RSI (14)')
            ax3.set_ylim(0, 100)
            ax3.legend(loc='upper left')
            ax3.grid(True, alpha=0.3)
            
            # Add latest price annotation
            last_price = df['close'].iloc[-1]
            ax1.annotate(f'${last_price:.2f}', 
                        xy=(df['time'].iloc[-1], last_price),
                        xytext=(10, 10), textcoords='offset points',
                        bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.5),
                        arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
            
            plt.tight_layout()
        
        # Animation
        ani = FuncAnimation(fig, update_chart, interval=10000, cache_frame_data=False)  # Update every 10 seconds
        
        plt.show()
        
    except ImportError:
        print("❌ Matplotlib tidak terinstall. Install dengan: pip install matplotlib")
        print("\n💡 Alternatif: Gunakan menu 1 (Analyze Now) untuk analisis manual")
    except Exception as e:
        print(f"❌ Error: {e}")


def menu_8_toggle_auto_trade(config: dict) -> dict:
    config["current"]["auto_trade"] = not config["current"]["auto_trade"]
    save_config(config)
    print(f"✅ Auto Trade diubah menjadi: {'ON' if config['current']['auto_trade'] else 'OFF'}")
    return config


def menu_9_set_auto_lot(config: dict) -> dict:
    try:
        new_lot = float(input("\nMasukkan ukuran lot (contoh: 0.01, 0.1): "))
        if 0 < new_lot <= 10:
            config["current"]["lot"] = new_lot
            save_config(config)
            print(f"✅ Lot diatur menjadi: {new_lot}")
        else:
            print("❌ Lot harus antara 0.01 dan 10!")
    except ValueError:
        print("❌ Input harus angka!")
    return config


def menu_10_set_auto_slippage(config: dict) -> dict:
    try:
        new_slip = int(input("\nMasukkan slippage (points): "))
        if new_slip >= 0:
            config["current"]["slippage"] = new_slip
            save_config(config)
            print(f"✅ Slippage diatur menjadi: {new_slip}")
        else:
            print("❌ Slippage tidak bisa negatif!")
    except ValueError:
        print("❌ Input harus angka!")
    return config


def menu_11_toggle_auto_close_profit(config: dict) -> dict:
    config["current"]["auto_close_profit"] = not config["current"]["auto_close_profit"]
    save_config(config)
    print(f"✅ Auto Close Profit diubah menjadi: {'ON' if config['current']['auto_close_profit'] else 'OFF'}")
    return config


def menu_12_set_auto_close_target(config: dict) -> dict:
    try:
        new_target = float(input("\nMasukkan target USD (contoh: 5.0): "))
        if new_target > 0:
            config["current"]["auto_close_target"] = new_target
            save_config(config)
            print(f"✅ Target Auto Close diatur menjadi: ${new_target}")
        else:
            print("❌ Target harus positif!")
    except ValueError:
        print("❌ Input harus angka!")
    return config


def menu_13_toggle_auto_analyze(config: dict) -> dict:
    config["current"]["auto_analyze"] = not config["current"]["auto_analyze"]
    save_config(config)
    print(f"✅ Auto Analyze diubah menjadi: {'ON' if config['current']['auto_analyze'] else 'OFF'}")
    return config


def menu_14_set_auto_analyze_interval(config: dict) -> dict:
    try:
        new_int = int(input("\nMasukkan interval (menit): "))
        if new_int > 0:
            config["current"]["auto_analyze_interval"] = new_int
            save_config(config)
            print(f"✅ Interval Auto Analyze diatur menjadi: {new_int} menit")
        else:
            print("❌ Interval harus positif!")
    except ValueError:
        print("❌ Input harus angka!")
    return config


def menu_15_toggle_bep(config: dict) -> dict:
    config["current"]["bep"] = not config["current"]["bep"]
    save_config(config)
    print(f"✅ BEP diubah menjadi: {'ON' if config['current']['bep'] else 'OFF'}")
    return config


def menu_16_set_bep_min_profit(config: dict) -> dict:
    try:
        new_profit = float(input("\nMasukkan BEP min profit (USD): "))
        if new_profit > 0:
            config["current"]["bep_min_profit"] = new_profit
            save_config(config)
            print(f"✅ BEP Min Profit diatur menjadi: ${new_profit}")
        else:
            print("❌ Profit harus positif!")
    except ValueError:
        print("❌ Input harus angka!")
    return config


def menu_17_set_bep_spread_multiplier(config: dict) -> dict:
    try:
        new_multi = float(input("\nMasukkan BEP spread multiplier (contoh: 1.0): "))
        if new_multi > 0:
            config["current"]["bep_spread_multiplier"] = new_multi
            save_config(config)
            print(f"✅ BEP Spread Multiplier diatur menjadi: {new_multi}")
        else:
            print("❌ Multiplier harus positif!")
    except ValueError:
        print("❌ Input harus angka!")
    return config


def menu_18_toggle_stpp_trailing(config: dict) -> dict:
    config["current"]["stpp_trailing"] = not config["current"]["stpp_trailing"]
    save_config(config)
    print(f"✅ STPP Trailing diubah menjadi: {'ON' if config['current']['stpp_trailing'] else 'OFF'}")
    return config


def menu_19_set_step_lock_init(config: dict) -> dict:
    try:
        new_init = float(input("\nMasukkan STEP Lock Init (USD): "))
        if new_init > 0:
            config["current"]["step_lock_init"] = new_init
            save_config(config)
            print(f"✅ STEP Lock Init diatur menjadi: ${new_init}")
        else:
            print("❌ Nilai harus positif!")
    except ValueError:
        print("❌ Input harus angka!")
    return config


def menu_20_set_step_step(config: dict) -> dict:
    try:
        new_step = float(input("\nMasukkan STEP Step (USD): "))
        if new_step > 0:
            config["current"]["step_step"] = new_step
            save_config(config)
            print(f"✅ STEP Step diatur menjadi: ${new_step}")
        else:
            print("❌ Nilai harus positif!")
    except ValueError:
        print("❌ Input harus angka!")
    return config


def menu_0_quit() -> bool:
    mt5.shutdown()
    print("\n👋 Menutup MT5 dan keluar...")
    return False


# Global variable for price triggers
price_triggers = []

def menu_21_set_one_shot(config: dict) -> None:
    """Set one-shot price trigger order"""
    print("\n🎯 SET PRICE TRIGGER ORDER")
    print("="*50)
    
    try:
        # Get inputs
        print("Enter trigger details:")
        symbol = input(f"Symbol [{config['current']['symbol']}]: ").strip() or config['current']['symbol']
        
        # Validate symbol
        if not select_symbol(symbol):
            print("❌ Invalid symbol")
            return
            
        side = input("Side (BUY/SELL): ").strip().upper()
        if side not in ['BUY', 'SELL']:
            print("❌ Side must be BUY or SELL")
            return
            
        trigger_price = float(input("Trigger Price: "))
        lot = float(input(f"Lot Size [{config['current']['lot']}]: ") or config['current']['lot'])
        
        # Get current price for reference
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            print(f"\n📊 Current Market:")
            print(f"Bid: {tick.bid:.5f} | Ask: {tick.ask:.5f}")
            
        # Optional SL/TP
        sl_input = input("Stop Loss (price or leave empty): ").strip()
        sl = float(sl_input) if sl_input else None
        
        tp_input = input("Take Profit (price or leave empty): ").strip()
        tp = float(tp_input) if tp_input else None
        
        # Create trigger
        trigger = {
            'id': len(price_triggers) + 1,
            'symbol': symbol,
            'side': side,
            'trigger_price': trigger_price,
            'lot': lot,
            'sl': sl,
            'tp': tp,
            'created_at': datetime.now(),
            'status': 'PENDING',
            'triggered': False
        }
        
        price_triggers.append(trigger)
        
        print("\n✅ Price Trigger Created:")
        print(f"ID: {trigger['id']}")
        print(f"Symbol: {symbol}")
        print(f"Side: {side}")
        print(f"Trigger: {trigger_price:.5f}")
        print(f"Lot: {lot}")
        if sl: print(f"SL: {sl:.5f}")
        if tp: print(f"TP: {tp:.5f}")
        print(f"Status: PENDING")
        
        # Start monitoring in background
        import threading
        monitor_thread = threading.Thread(target=monitor_price_triggers, daemon=True)
        monitor_thread.start()
        print("\n🔍 Price monitoring started...")
        
    except ValueError:
        print("❌ Invalid input format")
    except Exception as e:
        print(f"❌ Error: {e}")

def menu_22_cancel_price_trigger() -> None:
    """Cancel pending price triggers"""
    global price_triggers
    
    if not price_triggers:
        print("\n❌ No active price triggers")
        return
        
    print("\n📋 ACTIVE PRICE TRIGGERS")
    print("="*50)
    
    for trigger in price_triggers:
        if trigger['status'] == 'PENDING':
            print(f"ID: {trigger['id']} | {trigger['symbol']} | {trigger['side']} @ {trigger['trigger_price']:.5f}")
            print(f"   Lot: {trigger['lot']} | Created: {trigger['created_at'].strftime('%H:%M:%S')}")
            print("-"*50)
    
    try:
        trigger_id = input("\nEnter Trigger ID to cancel (or 'all' to cancel all): ").strip()
        
        if trigger_id.lower() == 'all':
            # Cancel all pending triggers
            cancelled = 0
            for trigger in price_triggers:
                if trigger['status'] == 'PENDING':
                    trigger['status'] = 'CANCELLED'
                    cancelled += 1
            print(f"✅ Cancelled {cancelled} triggers")
        else:
            # Cancel specific trigger
            trigger_id = int(trigger_id)
            for trigger in price_triggers:
                if trigger['id'] == trigger_id and trigger['status'] == 'PENDING':
                    trigger['status'] = 'CANCELLED'
                    print(f"✅ Trigger {trigger_id} cancelled")
                    return
            print(f"❌ Trigger {trigger_id} not found or already triggered")
            
    except ValueError:
        print("❌ Invalid input")

def monitor_price_triggers():
    """Background function to monitor price triggers"""
    import time
    
    while True:
        try:
            for trigger in price_triggers:
                if trigger['status'] != 'PENDING':
                    continue
                    
                # Get current price
                tick = mt5.symbol_info_tick(trigger['symbol'])
                if not tick:
                    continue
                    
                current_price = tick.bid if trigger['side'] == 'SELL' else tick.ask
                
                # Check if trigger hit
                triggered = False
                if trigger['side'] == 'BUY' and current_price <= trigger['trigger_price']:
                    triggered = True
                elif trigger['side'] == 'SELL' and current_price >= trigger['trigger_price']:
                    triggered = True
                    
                if triggered:
                    print(f"\n🔔 TRIGGER HIT! {trigger['symbol']} {trigger['side']} @ {current_price:.5f}")
                    
                    # Prepare order request
                    request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": trigger['symbol'],
                        "volume": trigger['lot'],
                        "type": mt5.ORDER_TYPE_BUY if trigger['side'] == 'BUY' else mt5.ORDER_TYPE_SELL,
                        "price": current_price,
                        "deviation": 20,
                        "magic": 234000,
                        "comment": f"Trigger #{trigger['id']}",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_IOC,
                    }
                    
                    # Add SL/TP if specified
                    if trigger['sl']:
                        request['sl'] = trigger['sl']
                    if trigger['tp']:
                        request['tp'] = trigger['tp']
                    
                    # Send order
                    result = mt5.order_send(request)
                    
                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        trigger['status'] = 'EXECUTED'
                        trigger['executed_price'] = current_price
                        trigger['executed_at'] = datetime.now()
                        trigger['ticket'] = result.order
                        print(f"✅ Order executed! Ticket: {result.order}")
                    else:
                        trigger['status'] = 'FAILED'
                        print(f"❌ Order failed: {result.comment}")
                        
            time.sleep(1)  # Check every second
            
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(5)


def menu_23_set_entry_decimals(config: dict) -> dict:
    try:
        new_dec = input("\nMasukkan entry decimals (contoh: None/0/1/2): ").strip().lower()
        if new_dec == "none":
            config["current"]["entry_decimals"] = None
        else:
            new_dec = int(new_dec)
            if 0 <= new_dec <= 2:
                config["current"]["entry_decimals"] = new_dec
            else:
                print("❌ Decimals harus 0,1,2, atau 'None'!")
                return config
        save_config(config)
        print(f"✅ Entry Decimals diatur menjadi: {config['current']['entry_decimals']}")
    except ValueError:
        print("❌ Input harus 'None', 0, 1, atau 2!")
    return config


def backtest_umum(config: dict, hari: int) -> None:
    print(f"\n🔄 Backtest {config['current']['symbol']} ({config['current']['timeframe']}) selama {hari} hari...")
    end_date = pd.Timestamp.now()
    start_date = end_date - pd.Timedelta(days=hari)
    
    mt5_start = start_date.timetuple()
    mt5_end = end_date.timetuple()
    mt5_tf = map_timeframe(config["current"]["timeframe"])
    
    data = mt5.copy_rates_range(
        config["current"]["symbol"],
        mt5_tf,
        mt5_start,
        mt5_end
    )
    
    if data is None:
        print(f"❌ Backtest gagal | Error: {mt5.last_error()}")
        return
    
    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    print(f"✅ Data backtest loaded | Baris: {len(df)} | Tanggal: {df['time'].min()} to {df['time'].max()}")
    print(df[["time", "open", "high", "low", "close"]].head(5))
    
    csv_name = f"backtest_{config['current']['symbol']}_{hari}d.csv"
    df.to_csv(csv_name, index=False)
    print(f"✅ Backtest disimpan ke: {csv_name}")


def menu_24_backtest_custom(config: dict) -> None:
    print("\n📅 Backtest Kustom: Masukkan tanggal (YYYY-MM-DD)")
    try:
        start_str = input("Tanggal Mulai: ")
        end_str = input("Tanggal Akhir: ")
        start_date = pd.Timestamp(start_str)
        end_date = pd.Timestamp(end_str)
        
        mt5_start = start_date.timetuple()
        mt5_end = end_date.timetuple()
        mt5_tf = map_timeframe(config["current"]["timeframe"])
        
        data = mt5.copy_rates_range(
            config["current"]["symbol"],
            mt5_tf,
            mt5_start,
            mt5_end
        )
        
        if data is None:
            print(f"❌ Backtest gagal | Error: {mt5.last_error()}")
            return
        
        df = pd.DataFrame(data)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        csv_name = f"backtest_{config['current']['symbol']}_kustom.csv"
        df.to_csv(csv_name, index=False)
        print(f"✅ Backtest kustom disimpan ke: {csv_name}")
    except Exception as e:
        print(f"❌ Format tanggal salah | Error: {str(e)}")


def menu_25_backtest_7d(config: dict) -> None:
    backtest_umum(config, hari=7)


def menu_26_backtest_14d(config: dict) -> None:
    backtest_umum(config, hari=14)


def menu_27_backtest_30d(config: dict) -> None:
    backtest_umum(config, hari=30)


def menu_28_backtest_60d(config: dict) -> None:
    backtest_umum(config, hari=60)


def menu_29_toggle_trade_always_on(config: dict) -> dict:
    config["current"]["trade_always_on"] = not config["current"]["trade_always_on"]
    save_config(config)
    print(f"✅ Trade Always On diubah menjadi: {'ON' if config['current']['trade_always_on'] else 'OFF'}")
    return config

def menu_30_change_mode_settings(config: dict) -> dict:
    """Advanced mode settings - SCALPING/AGGRESSIVE"""
    print("\n⚙️ TRADING MODE SETTINGS")
    print("="*60)
    print(f"Current Mode: {config['current']['trade_mode']}")
    print(f"Signal Threshold: {config['current'].get('min_signal_strength', 0.2):.0%}")
    print(f"Check Interval: {config['current']['auto_analyze_interval']} min")
    print("="*60)
    
    print("\n📊 PRESET MODES:")
    print("1) 🔥 SCALPING     - Ultra fast (5% threshold, 1min check, 100 trades/day)")
    print("2) ⚡ AGGRESSIVE   - Fast signals (10% threshold, 2min check, 50 trades/day)")
    print("3) 📈 MODERATE     - Balanced (20% threshold, 5min check, 20 trades/day)")
    print("4) 🛡️  CONSERVATIVE - Safe (35% threshold, 15min check, 10 trades/day)")
    print("5) ⚙️  CUSTOM       - Set your own values")
    print("0) ← Back")
    
    choice = input("\nSelect preset (0-5): ").strip()
    
    if choice == '0':
        return config
    
    presets = {
        '1': {
            'trade_mode': 'SCALPING',
            'min_signal_strength': 0.05,
            'auto_analyze_interval': 1,
            'max_daily_trades': 100,
            'enable_scalping': True,
            'enable_pattern_trading': True,
            'enable_breakout_trading': True,
            'signal_threshold': 'LOW'
        },
        '2': {
            'trade_mode': 'AGGRESSIVE',
            'min_signal_strength': 0.1,
            'auto_analyze_interval': 2,
            'max_daily_trades': 50,
            'enable_scalping': True,
            'enable_pattern_trading': True,
            'enable_breakout_trading': True,
            'signal_threshold': 'LOW'
        },
        '3': {
            'trade_mode': 'MODERATE',
            'min_signal_strength': 0.2,
            'auto_analyze_interval': 5,
            'max_daily_trades': 20,
            'enable_scalping': False,
            'enable_pattern_trading': True,
            'enable_breakout_trading': True,
            'signal_threshold': 'MEDIUM'
        },
        '4': {
            'trade_mode': 'CONSERVATIVE',
            'min_signal_strength': 0.35,
            'auto_analyze_interval': 15,
            'max_daily_trades': 10,
            'enable_scalping': False,
            'enable_pattern_trading': True,
            'enable_breakout_trading': False,
            'signal_threshold': 'HIGH'
        }
    }
    
    if choice in presets:
        # Apply preset
        for key, value in presets[choice].items():
            config['current'][key] = value
        
        save_config(config)
        
        print("\n✅ Settings Applied:")
        print(f"Mode: {config['current']['trade_mode']}")
        print(f"Threshold: {config['current']['min_signal_strength']:.0%}")
        print(f"Interval: {config['current']['auto_analyze_interval']} min")
        print(f"Max Trades: {config['current']['max_daily_trades']}/day")
        print(f"Scalping: {'✅' if config['current']['enable_scalping'] else '❌'}")
        print(f"Patterns: {'✅' if config['current']['enable_pattern_trading'] else '❌'}")
        print(f"Breakouts: {'✅' if config['current']['enable_breakout_trading'] else '❌'}")
        
    elif choice == '5':
        # Custom settings
        print("\n⚙️ CUSTOM SETTINGS:")
        try:
            threshold = float(input("Signal threshold (0.05-0.50, e.g., 0.1 for 10%): "))
            interval = int(input("Check interval in minutes (1-60): "))
            max_trades = int(input("Max daily trades (1-200): "))
            
            if 0.05 <= threshold <= 0.5 and 1 <= interval <= 60 and 1 <= max_trades <= 200:
                config['current']['min_signal_strength'] = threshold
                config['current']['auto_analyze_interval'] = interval
                config['current']['max_daily_trades'] = max_trades
                
                # Ask for features
                scalp = input("Enable scalping signals? (y/n): ").lower() == 'y'
                patterns = input("Enable pattern trading? (y/n): ").lower() == 'y'
                breakouts = input("Enable breakout trading? (y/n): ").lower() == 'y'
                
                config['current']['enable_scalping'] = scalp
                config['current']['enable_pattern_trading'] = patterns
                config['current']['enable_breakout_trading'] = breakouts
                config['current']['trade_mode'] = 'CUSTOM'
                
                save_config(config)
                print("\n✅ Custom settings saved!")
            else:
                print("❌ Invalid range!")
        except ValueError:
            print("❌ Invalid input!")
    else:
        print("❌ Invalid choice!")
    
    return config

def menu_31_setup_multi_position(config: dict) -> dict:
    """Setup multi-position trading"""
    print("\n⚙️ MULTI-POSITION SETUP")
    print("="*60)
    
    current = config['current']
    
    print(f"Current Settings:")
    print(f"  Max positions per symbol: {current.get('max_positions_per_symbol', 1)}")
    print(f"  Max total positions: {current.get('max_total_positions', 5)}")
    print(f"  Multi-symbol: {current.get('enable_multi_symbol', False)}")
    print(f"  Rapid fire mode: {current.get('rapid_fire_mode', False)}")
    
    print("\n📋 PRESETS:")
    print("1) 🐌 CONSERVATIVE - 1 position per symbol, max 3 total")
    print("2) 📈 MODERATE      - 3 positions per symbol, max 10 total")
    print("3) ⚡ AGGRESSIVE    - 5 positions per symbol, max 20 total")
    print("4) 🔥 RAPID FIRE    - 10 positions per symbol, max 50 total, multi-symbol")
    print("5) ⚙️  CUSTOM        - Set your own")
    print("0) ← Back")
    
    choice = input("\nSelect preset (0-5): ").strip()
    
    presets = {
        '1': {
            'max_positions_per_symbol': 1,
            'max_total_positions': 3,
            'enable_multi_symbol': False,
            'rapid_fire_mode': False,
            'max_daily_trades': 20
        },
        '2': {
            'max_positions_per_symbol': 3,
            'max_total_positions': 10,
            'enable_multi_symbol': False,
            'rapid_fire_mode': False,
            'max_daily_trades': 50
        },
        '3': {
            'max_positions_per_symbol': 5,
            'max_total_positions': 20,
            'enable_multi_symbol': True,
            'rapid_fire_mode': False,
            'max_daily_trades': 100
        },
        '4': {
            'max_positions_per_symbol': 10,
            'max_total_positions': 50,
            'enable_multi_symbol': True,
            'rapid_fire_mode': True,
            'enable_multi_timeframe': True,
            'max_daily_trades': 200,
            'auto_analyze_interval': 1,
            'symbols_to_trade': ['XAUUSDm', 'EURUSDm', 'GBPUSDm'],
            'timeframes_to_check': ['M1', 'M5', 'M15']
        }
    }
    
    if choice == '0':
        return config
    
    if choice in presets:
        for key, value in presets[choice].items():
            config['current'][key] = value
        
        save_config(config)
        
        print("\n✅ Settings Applied!")
        print(f"  Max positions per symbol: {config['current']['max_positions_per_symbol']}")
        print(f"  Max total positions: {config['current']['max_total_positions']}")
        print(f"  Max daily trades: {config['current']['max_daily_trades']}")
        print(f"  Rapid fire: {'✅' if config['current'].get('rapid_fire_mode') else '❌'}")
        
    elif choice == '5':
        try:
            per_symbol = int(input("Max positions per symbol (1-20): "))
            total = int(input("Max total positions (1-100): "))
            multi = input("Enable multi-symbol? (y/n): ").lower() == 'y'
            rapid = input("Enable rapid fire mode? (y/n): ").lower() == 'y'
            
            config['current']['max_positions_per_symbol'] = per_symbol
            config['current']['max_total_positions'] = total
            config['current']['enable_multi_symbol'] = multi
            config['current']['rapid_fire_mode'] = rapid
            
            save_config(config)
            print("\n✅ Custom settings saved!")
        except:
            print("❌ Invalid input")
    
    return config



def menu_99_start_trading(config: dict, gemini_client: genai.Client) -> None:
    """Start automated trading - SAFE with defaults"""
    
    # Ensure all required keys exist with defaults
    defaults = {
        'min_signal_strength': 0.1,
        'enable_scalping': True,
        'enable_pattern_trading': True,
        'enable_breakout_trading': True,
        'max_daily_trades': 50,
        'ignore_economic_calendar': False
    }
    
    for key, default_value in defaults.items():
        if key not in config['current']:
            config['current'][key] = default_value
    
    print("\n🚀 Starting Auto Trading...")
    print(f"Symbol: {config['current']['symbol']}")
    print(f"Timeframe: {config['current']['timeframe']}")
    print(f"Mode: {config['current']['trade_mode']}")
    print(f"Lot: {config['current']['lot']}")
    print(f"Min Signal: {config['current']['min_signal_strength']:.1%}")
    print(f"Max Daily Trades: {config['current']['max_daily_trades']}")
    print(f"Check Interval: {config['current']['auto_analyze_interval']} min")
    print(f"\nFeatures:")
    print(f"  Scalping: {'✅' if config['current']['enable_scalping'] else '❌'}")
    print(f"  Patterns: {'✅' if config['current']['enable_pattern_trading'] else '❌'}")
    print(f"  Breakouts: {'✅' if config['current']['enable_breakout_trading'] else '❌'}")
    
    # Initialize components
    try:
        analyzer = MarketAnalyzer(
            news_api_key=env.get('news_api_key'),
            te_key=env.get('trading_economics_key')
        )
        trader = TradeManager(config)
        bot = TradingBot(config, analyzer, trader, gemini_client)
        
        print("\n✅ All systems ready!")
        print("⚠️ Trading with AGGRESSIVE settings - expect MORE trades!")
        print("\nPress Ctrl+C to stop\n")
        
        bot.start()
        
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user.")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()

# --------------------------
# 5. LOOP UTAMA PROGRAM
# --------------------------
def main():
    config = load_config()
    if not config:
        return
    
    init_mt5()
    global gemini_client
    gemini_client = init_gemini()
    
    mapping_menu = {
        1: lambda c: menu_1_analyze_now(c, gemini_client),
        2: menu_2_change_symbol,
        3: menu_3_change_timeframe,
        4: menu_4_change_candles,
        5: menu_5_switch_account,
        6: menu_6_change_trade_mode,
        7: menu_7_launch_trainer,
        8: menu_8_toggle_auto_trade,
        9: menu_9_set_auto_lot,
        10: menu_10_set_auto_slippage,
        11: menu_11_toggle_auto_close_profit,
        12: menu_12_set_auto_close_target,
        13: menu_13_toggle_auto_analyze,
        14: menu_14_set_auto_analyze_interval,
        15: menu_15_toggle_bep,
        16: menu_16_set_bep_min_profit,
        17: menu_17_set_bep_spread_multiplier,
        18: menu_18_toggle_stpp_trailing,
        19: menu_19_set_step_lock_init,
        20: menu_20_set_step_step,
        0: menu_0_quit,
        21: menu_21_set_one_shot,
        22: menu_22_cancel_price_trigger,
        23: menu_23_set_entry_decimals,
        24: menu_24_backtest_custom,
        25: menu_25_backtest_7d,
        26: menu_26_backtest_14d,
        27: menu_27_backtest_30d,
        28: menu_28_backtest_60d,
        29: menu_29_toggle_trade_always_on,
        30: menu_30_change_mode_settings,
        31: menu_31_setup_multi_position,
        99: lambda c: menu_99_start_trading(c, gemini_client)
    }
    
    running = True
    while running:
        cetak_menu(config)
        pilihan = pilih_menu()
        
        if pilihan in mapping_menu:
            fungsi = mapping_menu[pilihan]
            
            if pilihan in [2,3,4,5,6,8,9,10,11,12,13,14,15,16,17,18,19,20,23,29,30,31]:
                config = mapping_menu[pilihan](config) # Panggil fungsi yang mengembalikan config
            elif pilihan == 0:
                running = mapping_menu[pilihan]()
            else:
                mapping_menu[pilihan](config) 
        
        time.sleep(0.5)


if __name__ == "__main__":
    main()