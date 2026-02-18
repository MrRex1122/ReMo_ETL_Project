import pandas as pd
import numpy as np
from datetime import datetime
import logging
import argparse
from config import get_price_converted_csv_path, get_catalog_csv_path

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PriceETL:
    """ETL Pipeline для очистки и нормализации прайс-листов (CSV из 1C/ETM)"""
    
    def __init__(self, input_path, output_path):
        self.input_path = input_path
        self.output_path = output_path
        self.df = None
        self.report = {}
    
    def extract(self):
        """Этап Extract: загрузка исходных данных"""
        logger.info(f"📥 Загрузка данных из {self.input_path}")
        self.df = pd.read_csv(
            self.input_path,
            sep=';',
            encoding='utf-8',
            decimal='.',
            low_memory=False
        )
        logger.info(f"✓ Загружено: {self.df.shape[0]} строк × {self.df.shape[1]} колонок")
        self.report['initial_rows'] = len(self.df)
        return self
    
    def transform(self):
        """Этап Transform: очистка и нормализация данных"""
        logger.info("🔧 Начало трансформации данных...")
        
        # 1. Удалить полностью пустые колонки
        initial_cols = len(self.df.columns)
        self.df = self.df.dropna(axis=1, how='all')
        logger.info(f"  ✓ Удалены пустые колонки: {initial_cols - len(self.df.columns)}")
        self.report['removed_empty_cols'] = initial_cols - len(self.df.columns)
        
        # 2. Удалить полностью пустые строки
        initial_rows = len(self.df)
        self.df = self.df.dropna(how='all')
        logger.info(f"  ✓ Удалены пустые строки: {initial_rows - len(self.df)}")
        self.report['removed_empty_rows'] = initial_rows - len(self.df)
        
        # 3. Удалить дубликаты (кроме первого вхождения)
        initial_rows = len(self.df)
        self.df = self.df.drop_duplicates()
        logger.info(f"  ✓ Удалены дубликаты: {initial_rows - len(self.df)}")
        self.report['removed_duplicates'] = initial_rows - len(self.df)
        
        # 4. Нормализация текстовых полей (удалить лишние пробелы)
        string_cols = self.df.select_dtypes(include=['object']).columns
        for col in string_cols:
            self.df[col] = self.df[col].str.strip()
        logger.info(f"  ✓ Нормализованы текстовые поля ({len(string_cols)} колонок)")
        
        # 5. Приведение регистра для категорий
        normalize_cols = ['Единица измерения', 'Название класса', 'Страна']
        for col in normalize_cols:
            if col in self.df.columns:
                self.df[col] = self.df[col].str.title()
        logger.info(f"  ✓ Приведен регистр в категорийных полях")
        
        # 6. Оптимизация числовых полей
        numeric_cols = self.df.select_dtypes(include=['float64', 'int64']).columns
        for col in numeric_cols:
            # Убрать нулевые значения если это цена или количество
            if any(x in col.lower() for x in ['цена', 'количество', 'вес', 'объем']):
                self.df = self.df[self.df[col] != 0]
        
        logger.info(f"  ✓ Обработаны числовые поля ({len(numeric_cols)} колонок)")
        
        # 7. Удалить колонки с >95% пропусков (малоинформативные)
        missing_ratio = self.df.isnull().sum() / len(self.df)
        cols_to_drop = missing_ratio[missing_ratio > 0.95].index.tolist()
        if cols_to_drop:
            self.df = self.df.drop(columns=cols_to_drop)
            logger.info(f"  ✓ Удалены колонки с >95% пропусков: {len(cols_to_drop)}")
            self.report['removed_sparse_cols'] = len(cols_to_drop)
        
        # 8. Заполнить пропуски в ключевых полях
        key_fields = {
            'Артикул': 'UNKNOWN',
            'Единица измерения': 'шт',
            'Ставка НДС': 20,
            'Страна': 'РФ'
        }
        for col, default_val in key_fields.items():
            if col in self.df.columns:
                self.df[col] = self.df[col].fillna(default_val)
        logger.info(f"  ✓ Заполнены пропуски в ключевых полях")
        
        logger.info("✓ Трансформация завершена")
        self.report['final_rows'] = len(self.df)
        
        return self
    
    def load(self):
        """Этап Load: сохранение очищенных данных"""
        logger.info(f"💾 Сохранение данных в {self.output_path}")
        self.df.to_csv(
            self.output_path,
            sep=';',
            encoding='utf-8',
            index=False
        )
        logger.info(f"✓ Данные сохранены: {len(self.df)} строк × {len(self.df.columns)} колонок")
        return self
    
    def generate_report(self):
        """Генерация отчета о трансформации"""
        logger.info("\n" + "="*60)
        logger.info("📊 ОТЧЕТ О ТРАНСФОРМАЦИИ ДАННЫХ")
        logger.info("="*60)
        logger.info(f"Исходное количество строк:     {self.report['initial_rows']}")
        logger.info(f"Финальное количество строк:    {self.report['final_rows']}")
        logger.info(f"Удалено строк:                 {self.report['initial_rows'] - self.report['final_rows']}")
        logger.info(f"Удалено пустых колонок:        {self.report.get('removed_empty_cols', 0)}")
        logger.info(f"Удалено разреженных колонок:   {self.report.get('removed_sparse_cols', 0)}")
        logger.info(f"Удалено дубликатов:            {self.report.get('removed_duplicates', 0)}")
        logger.info(f"Финальные колонки:             {len(self.df.columns)}")
        logger.info("="*60)
        logger.info(f"✅ ETL завершен успешно - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*60 + "\n")
    
    def run(self):
        """Запустить полный ETL pipeline"""
        self.extract().transform().load().generate_report()
        return self.df


# ============ ЗАПУСК ETL ============
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ETL for price list normalization")
    parser.add_argument("--input", default=str(get_price_converted_csv_path()), help="Path to source CSV")
    parser.add_argument("--output", default=str(get_catalog_csv_path()), help="Path to output clean CSV")
    args = parser.parse_args()

    etl = PriceETL(args.input, args.output)
    clean_df = etl.run()
    
    # Вывести статистику финального датасета
    print("\n📈 СТАТИСТИКА ФИНАЛЬНОГО ДАТАСЕТА:")
    print(f"Размер: {clean_df.shape}")
    print(f"Типы данных:\n{clean_df.dtypes.value_counts()}")
    print(f"\nПропуски:\n{clean_df.isnull().sum().sum()} всего (из {clean_df.size} ячеек)")
