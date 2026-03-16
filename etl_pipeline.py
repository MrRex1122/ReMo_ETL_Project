from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Iterator

import pandas as pd

from catalog_schema import (
    CANONICAL_ARTICLE_COLUMN,
    CANONICAL_NAME_COLUMN,
    CANONICAL_PRICE_COLUMN,
    REQUIRED_CATALOG_COLUMNS,
    canonicalize_catalog_columns,
)
from config import get_catalog_csv_path, get_price_converted_csv_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class PriceETL:
    """ETL pipeline for cleaning and normalizing supplier catalog CSV files."""

    def __init__(self, input_path: str | Path, output_path: str | Path):
        self.input_path = input_path
        self.output_path = output_path
        self.df: pd.DataFrame | None = None
        self.report: dict[str, int] = {}

    @staticmethod
    def _detect_csv_params(input_path: str | Path) -> tuple[str, str]:
        supported_encodings = ("utf-8-sig", "utf-8", "cp1251")
        supported_separators = (";", ",", "	")
        last_error: Exception | None = None

        for sep in supported_separators:
            for enc in supported_encodings:
                try:
                    probe = pd.read_csv(input_path, sep=sep, encoding=enc, decimal=".", low_memory=False, nrows=1000)
                    if probe.shape[1] <= 1:
                        continue
                    return sep, enc
                except (UnicodeDecodeError, pd.errors.ParserError, ValueError) as e:
                    last_error = e

        raise ValueError(f"Не удалось определить формат CSV: {input_path}. Ошибка: {last_error}")

    def extract(self) -> "PriceETL":
        logger.info(f"📥 Загрузка данных из {self.input_path}")
        sep, enc = self._detect_csv_params(self.input_path)
        logger.info(f"🧭 Определен формат CSV: sep={repr(sep)} encoding={enc}")
        self.df = pd.read_csv(
            self.input_path,
            sep=sep,
            encoding=enc,
            decimal=".",
            low_memory=False,
        )
        logger.info(f"✓ Загружено: {self.df.shape[0]} строк × {self.df.shape[1]} колонок")
        self.report["initial_rows"] = len(self.df)
        return self

    @staticmethod
    def _normalize_price_column(series: pd.Series) -> pd.Series:
        cleaned = (
            series.astype(str)
            .str.replace("\xa0", "", regex=False)
            .str.replace(" ", "", regex=False)
            .str.replace(",", ".", regex=False)
            .str.replace(r"[^\d\.\-]", "", regex=True)
        )
        return pd.to_numeric(cleaned, errors="coerce")

    @staticmethod
    def _has_text_value(series: pd.Series) -> pd.Series:
        normalized = series.fillna("").astype(str).str.strip()
        lowered = normalized.str.lower()
        return normalized.ne("") & ~lowered.isin({"nan", "none", "null", "nat"})

    def _has_identity_payload(self, df: pd.DataFrame) -> pd.Series:
        article_series = df.get(CANONICAL_ARTICLE_COLUMN)
        name_series = df.get(CANONICAL_NAME_COLUMN)
        if article_series is None or name_series is None:
            return pd.Series(False, index=df.index)
        return self._has_text_value(article_series) & self._has_text_value(name_series)

    def _drop_unidentified_duplicates(self, df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
        identity_mask = self._has_identity_payload(df)
        if identity_mask.all():
            return df, 0

        preserved_rows = df.loc[identity_mask]
        deduped_rows = df.loc[~identity_mask].drop_duplicates()
        removed_rows = int((~identity_mask).sum()) - len(deduped_rows)
        if preserved_rows.empty:
            return deduped_rows, removed_rows
        return pd.concat([preserved_rows, deduped_rows]).sort_index(kind="stable"), removed_rows

    def _drop_unidentified_zero_rows(self, df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
        removed_rows = 0
        for col in df.select_dtypes(include=["number"]).columns:
            lower_name = col.lower()
            if not any(marker in lower_name for marker in ("цена", "количество", "вес", "объем")):
                continue
            identity_mask = self._has_identity_payload(df)
            remove_mask = df[col].eq(0) & ~identity_mask
            if not remove_mask.any():
                continue
            removed_rows += int(remove_mask.sum())
            df = df.loc[~remove_mask]
        return df, removed_rows

    def _transform_dataframe(
        self,
        df: pd.DataFrame,
        *,
        drop_empty_columns: bool = True,
        drop_sparse_columns: bool = True,
    ) -> pd.DataFrame:
        df = canonicalize_catalog_columns(df, create_missing=True)

        if drop_empty_columns:
            empty_cols = [
                col for col in df.columns
                if df[col].isna().all() and col not in REQUIRED_CATALOG_COLUMNS
            ]
            if empty_cols:
                df = df.drop(columns=empty_cols)

        df = df.dropna(how="all")
        df, _ = self._drop_unidentified_duplicates(df)

        string_cols = df.select_dtypes(include=["object"]).columns
        for col in string_cols:
            df[col] = df[col].map(lambda value: value.strip() if isinstance(value, str) else value)

        for col in ("Единица измерения", "Название класса", "Страна"):
            if col in df.columns:
                df[col] = df[col].astype(str).str.title()

        if CANONICAL_PRICE_COLUMN in df.columns:
            df[CANONICAL_PRICE_COLUMN] = self._normalize_price_column(df[CANONICAL_PRICE_COLUMN])

        df, _ = self._drop_unidentified_zero_rows(df)

        if drop_sparse_columns:
            if len(df) > 0:
                missing_ratio = df.isnull().sum() / len(df)
                cols_to_drop = [
                    col for col in missing_ratio[missing_ratio > 0.95].index.tolist()
                    if col not in REQUIRED_CATALOG_COLUMNS
                ]
            else:
                cols_to_drop = []

            if cols_to_drop:
                df = df.drop(columns=cols_to_drop)

        key_fields = {
            "Единица измерения": "шт",
            "Ставка НДС": 20,
            "Страна": "РФ",
        }
        for col, default_val in key_fields.items():
            if col not in df.columns:
                continue
            if df[col].dtype == object:
                df[col] = df[col].replace(r"^\s*$", pd.NA, regex=True)
            df[col] = df[col].fillna(default_val)

        return df

    def transform(self) -> "PriceETL":
        if self.df is None:
            raise RuntimeError("extract() must be called before transform()")

        logger.info("🔧 Начало трансформации данных...")

        # Map alternative supplier headers (e.g. "Код товара", "SKU") to canonical columns.
        self.df = canonicalize_catalog_columns(self.df, create_missing=True)
        present_required = [col for col in REQUIRED_CATALOG_COLUMNS if col in self.df.columns]
        logger.info(f"  ✓ Канонические колонки: {', '.join(present_required)}")

        # 1. Drop fully empty columns, but keep required catalog columns.
        initial_cols = len(self.df.columns)
        empty_cols = [
            col for col in self.df.columns
            if self.df[col].isna().all() and col not in REQUIRED_CATALOG_COLUMNS
        ]
        if empty_cols:
            self.df = self.df.drop(columns=empty_cols)
        removed_empty_cols = initial_cols - len(self.df.columns)
        logger.info(f"  ✓ Удалены пустые колонки: {removed_empty_cols}")
        self.report["removed_empty_cols"] = removed_empty_cols

        # 2. Drop fully empty rows.
        initial_rows = len(self.df)
        self.df = self.df.dropna(how="all")
        removed_empty_rows = initial_rows - len(self.df)
        logger.info(f"  ✓ Удалены пустые строки: {removed_empty_rows}")
        self.report["removed_empty_rows"] = removed_empty_rows

        # 3. Drop duplicate rows.
        self.df, removed_duplicates = self._drop_unidentified_duplicates(self.df)
        logger.info(f"  ✓ Удалены дубликаты без артикула и наименования: {removed_duplicates}")
        self.report["removed_duplicates"] = removed_duplicates

        # 4. Trim spaces in string columns.
        string_cols = self.df.select_dtypes(include=["object"]).columns
        for col in string_cols:
            self.df[col] = self.df[col].map(lambda value: value.strip() if isinstance(value, str) else value)
        logger.info(f"  ✓ Нормализованы текстовые поля ({len(string_cols)} колонок)")

        # 5. Normalize category-like fields to title case.
        for col in ("Единица измерения", "Название класса", "Страна"):
            if col in self.df.columns:
                self.df[col] = self.df[col].astype(str).str.title()
        logger.info("  ✓ Приведен регистр в категорийных полях")

        # 6. Normalize canonical retail price if present.
        if CANONICAL_PRICE_COLUMN in self.df.columns:
            self.df[CANONICAL_PRICE_COLUMN] = self._normalize_price_column(self.df[CANONICAL_PRICE_COLUMN])

        numeric_cols = self.df.select_dtypes(include=["number"]).columns
        self.df, removed_zero_rows = self._drop_unidentified_zero_rows(self.df)
        logger.info(
            f"  ✓ Обработаны числовые поля ({len(numeric_cols)} колонок), "
            f"удалены строки без артикула и наименования с нулевыми значениями: {removed_zero_rows}"
        )
        self.report["removed_zero_value_rows"] = removed_zero_rows

        # 7. Drop sparse columns (>95% missing), but keep required columns.
        if len(self.df) > 0:
            missing_ratio = self.df.isnull().sum() / len(self.df)
            cols_to_drop = [
                col
                for col in missing_ratio[missing_ratio > 0.95].index.tolist()
                if col not in REQUIRED_CATALOG_COLUMNS
            ]
        else:
            cols_to_drop = []

        if cols_to_drop:
            self.df = self.df.drop(columns=cols_to_drop)
        logger.info(f"  ✓ Удалены колонки с >95% пропусков: {len(cols_to_drop)}")
        self.report["removed_sparse_cols"] = len(cols_to_drop)

        # 8. Fill missing values in key fields.
        key_fields = {
            "Единица измерения": "шт",
            "Ставка НДС": 20,
            "Страна": "РФ",
        }
        for col, default_val in key_fields.items():
            if col not in self.df.columns:
                continue
            if self.df[col].dtype == object:
                self.df[col] = self.df[col].replace(r"^\s*$", pd.NA, regex=True)
            self.df[col] = self.df[col].fillna(default_val)
        logger.info("  ✓ Заполнены пропуски в ключевых полях")

        logger.info("✓ Трансформация завершена")
        self.report["final_rows"] = len(self.df)
        return self

    def load(self) -> "PriceETL":
        if self.df is None:
            raise RuntimeError("transform() must be called before load()")

        logger.info(f"💾 Сохранение данных в {self.output_path}")
        output_path = Path(self.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.df.to_csv(output_path, sep=";", encoding="utf-8", index=False)
        logger.info(f"✓ Данные сохранены: {len(self.df)} строк × {len(self.df.columns)} колонок")
        return self

    def generate_report(self) -> None:
        if self.df is None:
            raise RuntimeError("transform() must be called before generate_report()")

        logger.info("\n" + "=" * 60)
        logger.info("📊 ОТЧЕТ О ТРАНСФОРМАЦИИ ДАННЫХ")
        logger.info("=" * 60)
        logger.info(f"Исходное количество строк:     {self.report.get('initial_rows', 0)}")
        logger.info(f"Финальное количество строк:    {self.report.get('final_rows', 0)}")
        logger.info(
            f"Удалено строк:                 "
            f"{self.report.get('initial_rows', 0) - self.report.get('final_rows', 0)}"
        )
        logger.info(f"Удалено пустых колонок:        {self.report.get('removed_empty_cols', 0)}")
        logger.info(f"Удалено разреженных колонок:   {self.report.get('removed_sparse_cols', 0)}")
        logger.info(f"Удалено дубликатов:            {self.report.get('removed_duplicates', 0)}")
        logger.info(f"Удалено строк с нулями:        {self.report.get('removed_zero_value_rows', 0)}")
        logger.info(f"Финальные колонки:             {len(self.df.columns)}")
        logger.info("=" * 60)
        logger.info(f"✅ ETL завершен успешно - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60 + "\n")

    def run(self) -> pd.DataFrame:
        self.extract().transform().load().generate_report()
        return self.df

    def run_chunked(self, *, chunksize: int = 100000) -> pd.DataFrame:
        """Memory-safe ETL for very large CSV by processing chunks."""
        sep, enc = self._detect_csv_params(self.input_path)
        output_path = Path(self.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if output_path.exists():
            output_path.unlink()

        total_in = 0
        total_out = 0
        first_chunk = True

        logger.info("🚚 Chunked ETL старт: file=%s chunksize=%s", self.input_path, chunksize)
        for chunk_idx, chunk in enumerate(
            pd.read_csv(
                self.input_path,
                sep=sep,
                encoding=enc,
                decimal=".",
                low_memory=False,
                chunksize=chunksize,
            ),
            start=1,
        ):
            total_in += len(chunk)
            transformed = self._transform_dataframe(
                chunk,
                drop_empty_columns=False,
                drop_sparse_columns=False,
            )
            total_out += len(transformed)
            transformed.to_csv(
                output_path,
                sep=";",
                encoding="utf-8",
                index=False,
                mode="w" if first_chunk else "a",
                header=first_chunk,
            )
            first_chunk = False
            logger.info(
                "📦 Chunk %s: in=%s out=%s total_out=%s",
                chunk_idx,
                len(chunk),
                len(transformed),
                total_out,
            )

        self.report["initial_rows"] = total_in
        self.report["final_rows"] = total_out
        logger.info("✅ Chunked ETL завершен: in=%s out=%s", total_in, total_out)
        return pd.DataFrame()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ETL for price list normalization")
    parser.add_argument("--input", default=str(get_price_converted_csv_path()), help="Path to source CSV")
    parser.add_argument("--output", default=str(get_catalog_csv_path()), help="Path to output clean CSV")
    args = parser.parse_args()

    etl = PriceETL(args.input, args.output)
    clean_df = etl.run()

    print("\n📈 СТАТИСТИКА ФИНАЛЬНОГО ДАТАСЕТА:")
    print(f"Размер: {clean_df.shape}")
    print(f"Типы данных:\n{clean_df.dtypes.value_counts()}")
    print(f"\nПропуски:\n{clean_df.isnull().sum().sum()} всего (из {clean_df.size} ячеек)")
