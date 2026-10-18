# KvestCity Parser

Парсер хоррор-квестов Москвы с [kvest-moscow.ru](https://kvest-moscow.ru).

## Что собирает
Название, цена, адрес, кол-во игроков, длительность, возраст, сложность, описание, URL.

## Стек
Python 3.14, Playwright, pandas, openpyxl.

## Результат
83 квеста, отсортированы по цене, CSV + XLSX.


## Запуск
pip install -r requirements.txt
playwright install chromium
python parser.py
