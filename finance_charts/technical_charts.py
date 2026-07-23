from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf


def download_history(ticker, period="1y"):
    df = yf.Ticker(ticker).history(period=period, actions=False, auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError(f"No market data found for {ticker}")
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    return df


def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def stochastic(df, period=14, smooth=3):
    low_min = df["Low"].rolling(period).min()
    high_max = df["High"].rolling(period).max()
    k = 100 * (df["Close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    d = k.rolling(smooth).mean()
    return k, d


def williams_r(df, period=14):
    high_max = df["High"].rolling(period).max()
    low_min = df["Low"].rolling(period).min()
    return -100 * (high_max - df["Close"]) / (high_max - low_min).replace(0, np.nan)


def macd(close, fast=12, slow=26, signal=9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(df, period=14):
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(period).mean()


def adx_di(df, period=14):
    up_move = df["High"].diff()
    down_move = -df["Low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr_values = atr(df, period)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(period).mean() / atr_values
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(period).mean() / atr_values
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_values = dx.rolling(period).mean()
    return adx_values, plus_di, minus_di


def add_indicators(df):
    out = df.copy()
    out["EMA9"] = ema(out["Close"], 9)
    out["EMA21"] = ema(out["Close"], 21)
    out["EMA30"] = ema(out["Close"], 30)
    out["EMA50"] = ema(out["Close"], 50)
    out["Alligator_Jaw"] = out["Close"].rolling(13).mean().shift(8)
    out["Alligator_Teeth"] = out["Close"].rolling(8).mean().shift(5)
    out["Alligator_Lips"] = out["Close"].rolling(5).mean().shift(3)
    out["RSI"] = rsi(out["Close"])
    out["Stoch_K"], out["Stoch_D"] = stochastic(out)
    out["Williams_R"] = williams_r(out)
    out["MACD"], out["MACD_Signal"], out["MACD_Hist"] = macd(out["Close"])
    out["ADX"], out["PLUS_DI"], out["MINUS_DI"] = adx_di(out)
    out["Vol_MA10"] = out["Volume"].rolling(10).mean()
    out["Vol_MA5"] = out["Volume"].rolling(5).mean()
    return out


def _plot_candles(ax, df):
    x = _date_positions(df)
    width = 0.6
    for xpos, row in zip(x, df.itertuples()):
        color = "#16a34a" if row.Close >= row.Open else "#ef4444"
        ax.vlines(xpos, row.Low, row.High, color=color, linewidth=1.0, alpha=0.9)
        bottom = min(row.Open, row.Close)
        height = max(abs(row.Close - row.Open), 0.001)
        rect = plt.Rectangle((xpos - width / 2, bottom), width, height, color=color, alpha=0.65)
        ax.add_patch(rect)
    ax.set_xlim(-1, len(df))


def _date_positions(df):
    return np.arange(len(df))


def _decorate_position_axis(ax, df, max_ticks=9):
    if df.empty:
        return
    step = max(1, int(np.ceil(len(df) / max_ticks)))
    ticks = list(range(0, len(df), step))
    if ticks[-1] != len(df) - 1:
        ticks.append(len(df) - 1)
    labels = [df.index[i].strftime("%Y-%m-%d") for i in ticks]
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels)
    for label in ax.get_xticklabels():
        label.set_rotation(35)
        label.set_ha("right")


def _save(fig, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def plot_price_alligator(df, ticker, output_path, days=70, chart_type="candlestick"):
    view = df.tail(days).copy()
    x = _date_positions(view)
    fig, ax = plt.subplots(figsize=(15, 6))
    if chart_type == "candlestick":
        _plot_candles(ax, view)
    else:
        ax.plot(x, view["Close"], label="Close", color="#111827", linewidth=2)

    ax.plot(x, view["Alligator_Jaw"], label="Jaw", color="blue", linewidth=1.6)
    ax.plot(x, view["Alligator_Teeth"], label="Teeth", color="red", linewidth=1.6)
    ax.plot(x, view["Alligator_Lips"], label="Lips", color="green", linewidth=1.6)
    ax.plot(x, view["EMA30"], label="EMA30", color="#db2777", linewidth=1.2)
    ax.plot(x, view["EMA50"], label="EMA50", color="#f97316", linewidth=1.2)

    last_close = view["Close"].iloc[-1]
    ax.axhline(last_close, color="#2563eb", linestyle="--", linewidth=1, alpha=0.7, label=f"Close {last_close:.3f}")
    ax.set_title(f"{ticker} - Price & Alligator (last {len(view)} bars)")
    ax.set_ylabel("Price")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", ncol=2)
    _decorate_position_axis(ax, view)
    return _save(fig, output_path)


def plot_momentum_dashboard(df, ticker, output_path, days=70):
    view = df.tail(days).copy()
    x = _date_positions(view)
    fig, axes = plt.subplots(3, 1, figsize=(15, 10), sharex=True)

    up = view["Close"] >= view["Open"]
    colors = np.where(up, "#16a34a", "#ef4444")
    axes[0].bar(x, view["Volume"], color=colors, alpha=0.8, label="Volume")
    axes[0].plot(x, view["Vol_MA10"], color="#2563eb", label="Vol MA10")
    axes[0].plot(x, view["Vol_MA5"], color="#f97316", label="Vol MA5")
    axes[0].set_title("Volume + MA10 MA5")
    axes[0].legend(loc="upper left")

    axes[1].plot(x, view["RSI"], color="#f59e0b", label="RSI")
    axes[1].plot(x, view["Stoch_K"], color="#2563eb", label="Stoch K")
    axes[1].plot(x, view["Stoch_D"], color="#ef4444", label="Stoch D")
    axes[1].axhline(70, color="#2563eb", linestyle=":", linewidth=2, alpha=0.6)
    axes[1].axhline(50, color="#f97316", linestyle=":", linewidth=1.5, alpha=0.6)
    axes[1].axhline(30, color="#16a34a", linestyle=":", linewidth=2, alpha=0.6)
    axes[1].set_ylim(0, 100)
    ax_w = axes[1].twinx()
    ax_w.plot(x, view["Williams_R"], color="#38bdf8", label="Williams %R")
    ax_w.set_ylim(-105, 5)
    axes[1].set_title("RSI / Stoch / Williams%R")
    h1, l1 = axes[1].get_legend_handles_labels()
    h2, l2 = ax_w.get_legend_handles_labels()
    axes[1].legend(h1 + h2, l1 + l2, loc="upper left", ncol=2)

    hist_colors = np.where(view["MACD_Hist"] >= 0, "#16a34a", "#ef4444")
    axes[2].bar(x, view["MACD_Hist"], color=hist_colors, alpha=0.65, label="MACD Histogram")
    axes[2].plot(x, view["MACD"], color="blue", label="MACD")
    axes[2].plot(x, view["MACD_Signal"], color="red", label="MACD Signal")
    axes[2].axhline(0, color="#374151", linestyle="--", linewidth=1, alpha=0.6)
    axes[2].set_title("MACD / Signal / Histogram")
    axes[2].legend(loc="upper left")

    for ax in axes:
        ax.grid(True, alpha=0.3)
    _decorate_position_axis(axes[-1], view)
    fig.suptitle(f"{ticker} - momentum dashboard", fontweight="bold")
    fig.subplots_adjust(hspace=0.35)
    return _save(fig, output_path)


def plot_adx_dashboard(df, ticker, output_path, days=70):
    view = df.tail(days).copy()
    x = _date_positions(view)
    fig, ax = plt.subplots(figsize=(15, 4))
    ax.plot(x, view["PLUS_DI"], color="#2563eb", label="DI+")
    ax.plot(x, view["MINUS_DI"], color="#f97316", label="DI-")
    ax.plot(x, view["ADX"], color="#16a34a", linewidth=2, label="ADX")
    ax.axhline(25, color="#ef4444", linestyle="--", linewidth=1, alpha=0.6)
    ax.text(x[-1], 25, " 25", va="center", fontsize=9)
    ax.set_title(f"{ticker} - ADX + DI (25 = trend strength)")
    ax.set_ylabel("ADX / DI")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left")
    _decorate_position_axis(ax, view)
    return _save(fig, output_path)


def latest_snapshot(df):
    last = df.dropna(subset=["Close"]).iloc[-1]
    previous = df.dropna(subset=["Close"]).iloc[-2]
    recent_10 = df.dropna(subset=["High", "Low", "Close"]).tail(10)
    recent_30 = df.dropna(subset=["High", "Low", "Close"]).tail(30)
    close = float(last["Close"])
    support_10 = float(recent_10["Low"].min())
    support_30 = float(recent_30["Low"].min())
    resistance_10 = float(recent_10["High"].max())
    resistance_30 = float(recent_30["High"].max())

    def pct_distance(level):
        return float((level / close - 1) * 100)

    return {
        "date": str(last.name.date()),
        "close": close,
        "change_1d_pct": float((last["Close"] / previous["Close"] - 1) * 100),
        "rsi": float(last.get("RSI", np.nan)),
        "macd": float(last.get("MACD", np.nan)),
        "macd_signal": float(last.get("MACD_Signal", np.nan)),
        "stoch_k": float(last.get("Stoch_K", np.nan)),
        "stoch_d": float(last.get("Stoch_D", np.nan)),
        "williams_r": float(last.get("Williams_R", np.nan)),
        "adx": float(last.get("ADX", np.nan)),
        "plus_di": float(last.get("PLUS_DI", np.nan)),
        "minus_di": float(last.get("MINUS_DI", np.nan)),
        "volume": float(last.get("Volume", np.nan)),
        "volume_ma10": float(last.get("Vol_MA10", np.nan)),
        "volume_ma5": float(last.get("Vol_MA5", np.nan)),
        "support_10": support_10,
        "support_10_dist_pct": pct_distance(support_10),
        "support_30": support_30,
        "support_30_dist_pct": pct_distance(support_30),
        "resistance_10": resistance_10,
        "resistance_10_dist_pct": pct_distance(resistance_10),
        "resistance_30": resistance_30,
        "resistance_30_dist_pct": pct_distance(resistance_30),
    }


def create_chart_bundle(ticker, output_dir, period="1y", days=70, chart_type="candlestick"):
    output_dir = Path(output_dir)
    df = add_indicators(download_history(ticker, period=period))
    safe_ticker = ticker.replace("/", "_")
    files = [
        plot_price_alligator(df, ticker, output_dir / f"{safe_ticker}_price_alligator.png", days, chart_type),
        plot_momentum_dashboard(df, ticker, output_dir / f"{safe_ticker}_momentum.png", days),
        plot_adx_dashboard(df, ticker, output_dir / f"{safe_ticker}_adx.png", days),
    ]
    return {"ticker": ticker, "files": files, "snapshot": latest_snapshot(df)}


def create_snapshot_bundle(ticker, period="1y"):
    df = add_indicators(download_history(ticker, period=period))
    return {"ticker": ticker, "files": [], "snapshot": latest_snapshot(df)}
