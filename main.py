import pandas as pd
import argparse
from config import get_price_raw_csv_path, get_price_converted_csv_path

parser = argparse.ArgumentParser(description="Convert source price CSV to UTF-8")
parser.add_argument("--input", default=str(get_price_raw_csv_path()), help="Path to source price.csv")
parser.add_argument("--output", default=str(get_price_converted_csv_path()), help="Path to converted CSV")
args = parser.parse_args()

df = pd.read_csv(
    args.input,
    sep=";",
    encoding="cp1251",
    decimal=".",
    low_memory=False
)

# если парсер/логика ломается из-за пустого последнего столбца:
if df.columns[-1].startswith("Unnamed") or df.columns[-1] == "":
    df = df.iloc[:, :-1]

print(df.shape)
print(df.head(3))

# Сохранить конвертированный файл в UTF-8
output_path = args.output
df.to_csv(output_path, sep=";", encoding="utf-8", index=False)
print(f"\n✓ Файл сохранен: {output_path}")
