"""Загрузка часовых свечей из публичного архива Binance (https://data.binance.vision).

Архив не требует ключей API. За каждый месяц лежит один zip-файл с CSV.
Скрипт скачивает все месяцы подряд, склеивает их и сохраняет в data/raw/.

Запуск из корня репозитория:
    python src/download_data.py
"""

import io
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://data.binance.vision/data"
INTERVAL = "1h"
START = "2020-01"  # с января 2020 в архиве есть и спот, и фьючерсы
END = "2026-10"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

# (рынок, тикер): spot — спотовый рынок, futures — бессрочный фьючерс USDⓈ-M
SERIES = [
    ("spot", "BTCUSDT"),
    ("futures", "BTCUSDT"),
    ("spot", "ETHUSDT"),
    ("spot", "SOLUSDT"),
]

COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "trades", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]


def month_url(market: str, symbol: str, month: str) -> str:
    prefix = "spot" if market == "spot" else "futures/um"
    return f"{BASE_URL}/{prefix}/monthly/klines/{symbol}/{INTERVAL}/{symbol}-{INTERVAL}-{month}.zip"


def to_datetime_utc(ts: pd.Series) -> pd.Series:
    """Переводит время Binance в дату.

    До 2025 года время в файлах записано в миллисекундах (13 цифр),
    в спотовых файлах с 2025 года — в микросекундах (16 цифр).
    """
    ts = ts.astype("int64")
    ms = ts.where(ts < 10**14, ts // 1000)
    return pd.to_datetime(ms, unit="ms")


def read_month(market: str, symbol: str, month: str) -> pd.DataFrame | None:
    """Скачивает один месяц. Возвращает None, если файла в архиве нет."""
    for attempt in range(3):
        try:
            response = requests.get(month_url(market, symbol, month), timeout=60)
            break
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"Не удалось скачать {market} {symbol} {month}")

    if response.status_code == 404:
        return None
    response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        with archive.open(archive.namelist()[0]) as csv_file:
            df = pd.read_csv(csv_file, header=None, names=COLUMNS, dtype=str)

    # в части файлов первая строка — заголовок, в части его нет
    if df.iloc[0, 0] == "open_time":
        df = df.iloc[1:]

    df = df.drop(columns=["ignore", "close_time"])
    df["open_time"] = to_datetime_utc(df["open_time"])
    for col in df.columns.drop("open_time"):
        df[col] = pd.to_numeric(df[col])
    df["trades"] = df["trades"].astype("int64")
    return df


def download_series(market: str, symbol: str) -> pd.DataFrame:
    months = pd.period_range(START, END, freq="M").astype(str)
    parts, missing_months = [], []
    for month in months:
        part = read_month(market, symbol, month)
        if part is None:
            missing_months.append(month)
        else:
            parts.append(part)
    df = pd.concat(parts, ignore_index=True)
    if missing_months:
        print(f"  нет в архиве: {missing_months[0]} … {missing_months[-1]} ({len(missing_months)} мес.)")
    return df


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for market, symbol in SERIES:
        print(f"{market} {symbol}")
        df = download_series(market, symbol)
        path = OUT_DIR / f"{market}_{symbol}_{INTERVAL}.csv.gz"
        # сохраняем «как есть»: пропуски и дубли ищем уже в EDA.ipynb
        df.to_csv(path, index=False)
        print(f"  строк: {len(df):,}; {df['open_time'].min()} … {df['open_time'].max()} -> {path.name}")


if __name__ == "__main__":
    main()
