import pandas as pd

df = pd.read_csv(
    r"D:\Data\Downloads\upload\price.csv",
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
output_path = r"D:\Data\Downloads\upload\price_converted.csv"
df.to_csv(output_path, sep=";", encoding="utf-8", index=False)
print(f"\n✓ Файл сохранен: {output_path}")