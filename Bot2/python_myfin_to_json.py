import requests
from bs4 import BeautifulSoup
import json
import logging
import ast

# Настройка логирования
logging.basicConfig(filename='parser.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# URL страницы Myfin.by
MYFIN_URL = 'https://myfin.by/currency/minsk'

# Заголовки для имитации браузера
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://myfin.by/",
    "Connection": "keep-alive"
}

OUTPUT_FILE = "bank_rates.json"


def parse_and_save_rates():
    try:
        response = requests.get(MYFIN_URL, headers=HEADERS, timeout=10)
        response.raise_for_status()

        logging.info(f"Статус ответа: {response.status_code}")
        logging.debug(f"Первые 500 символов HTML: {response.text[:500]}")

        soup = BeautifulSoup(response.text, 'html.parser')

        # Извлекаем строки таблицы
        rows = soup.find_all('tr')
        if not rows:
            logging.error("Не найдено строк на странице")
            return False

        rates = []
        seen_banks = set()  # Для избежания дубликатов
        current_bank = None
        current_branches = []

        for i, row in enumerate(rows):
            # Проверяем, есть ли в строке название банка
            bank_name = None
            if i < 7:  # Первые 7 банков
                bank_elem = row.find(class_='fake-link js_link_blank')
                if bank_elem:
                    bank_name = bank_elem.text.strip()
            else:  # Банки после первых 7
                bank_elem = row.find(class_='pos-r')
                if bank_elem:
                    bank_name = bank_elem.text.strip()

            # Если нашли название банка, сохраняем предыдущий банк, если он есть
            if bank_name and current_bank:
                # Извлекаем курсы для предыдущего банка
                cells = rows[i - 1].find_all(class_='currencies-courses__currency-cell')
                if len(cells) < 4:
                    logging.warning(
                        f"Недостаточно ячеек с курсами для банка {current_bank}: {[cell.text.strip() for cell in cells]}")
                else:
                    try:
                        usd_buy = float(cells[0].text.strip()) if cells[0].text.strip() != '—' else 0.0
                        usd_sell = float(cells[1].text.strip()) if cells[1].text.strip() != '—' else 0.0
                        eur_buy = float(cells[2].text.strip()) if cells[2].text.strip() != '—' else 0.0
                        eur_sell = float(cells[3].text.strip()) if cells[3].text.strip() != '—' else 0.0
                    except ValueError as e:
                        logging.error(
                            f"Ошибка преобразования курса для банка {current_bank}: {[cell.text.strip() for cell in cells]} - {e}")
                        continue

                    # Проверяем уникальность записи
                    bank_key = f"{current_bank}-{usd_buy}-{usd_sell}-{eur_buy}-{eur_sell}"
                    if bank_key not in seen_banks:
                        seen_banks.add(bank_key)
                        rates.append({
                            'bank': current_bank,
                            'branches': current_branches,
                            'USD': {'buy': usd_buy, 'sell': usd_sell},
                            'EUR': {'buy': eur_buy, 'sell': eur_sell}
                        })

                current_branches = []  # Сбрасываем список отделений для нового банка
                current_bank = bank_name

            # Если это первый банк в списке
            elif bank_name:
                current_bank = bank_name

            # Извлекаем адрес и координаты отделения
            branch_elem = row.find(class_='currencies-courses__branch-name')
            coords_elem = row.find(class_='currencies-courses__icon-cell')
            if branch_elem and current_bank and coords_elem:
                branch_name = branch_elem.text.strip().rstrip(',')
                coords_str = coords_elem.get('data-fillial-coords', '')
                if coords_str:
                    try:
                        # Парсим строку как список координат
                        coords_list = ast.literal_eval(coords_str.replace(' ', ''))
                        for coords in coords_list:
                            lat, lon = map(float, coords.split(','))
                            if branch_name not in [b['address'] for b in current_branches]:
                                current_branches.append({
                                    'address': branch_name,
                                    'coords': (lat, lon)
                                })
                                break  # Берем первую пару координат для данного адреса
                    except (ValueError, SyntaxError) as e:
                        logging.warning(f"Некорректный формат координат для адреса {branch_name}: {coords_str} - {e}")
                        if branch_name not in [b['address'] for b in current_branches]:
                            current_branches.append({'address': branch_name})
                else:
                    if branch_name not in [b['address'] for b in current_branches]:
                        current_branches.append({'address': branch_name})

        # Сохраняем последний банк
        if current_bank and current_branches:
            cells = rows[-1].find_all(class_='currencies-courses__currency-cell')
            if len(cells) >= 4:
                try:
                    usd_buy = float(cells[0].text.strip()) if cells[0].text.strip() != '—' else 0.0
                    usd_sell = float(cells[1].text.strip()) if cells[1].text.strip() != '—' else 0.0
                    eur_buy = float(cells[2].text.strip()) if cells[2].text.strip() != '—' else 0.0
                    eur_sell = float(cells[3].text.strip()) if cells[3].text.strip() != '—' else 0.0

                    bank_key = f"{current_bank}-{usd_buy}-{usd_sell}-{eur_buy}-{eur_sell}"
                    if bank_key not in seen_banks:
                        seen_banks.add(bank_key)
                        rates.append({
                            'bank': current_bank,
                            'branches': current_branches,
                            'USD': {'buy': usd_buy, 'sell': usd_sell},
                            'EUR': {'buy': eur_buy, 'sell': eur_sell}
                        })
                except ValueError as e:
                    logging.error(
                        f"Ошибка преобразования курса для последнего банка {current_bank}: {[cell.text.strip() for cell in cells]} - {e}")

        if not rates:
            logging.error("Не удалось извлечь ни одного курса валют")
            return False

        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(rates, f, ensure_ascii=False, indent=4)

        logging.info(f"Курсы успешно спарсены и сохранены в {OUTPUT_FILE}")
        return True

    except requests.RequestException as e:
        logging.error(f"Ошибка при получении данных с Myfin.by: {e}")
        return False
    except Exception as e:
        logging.error(f"Общая ошибка при парсинге Myfin.by: {e}")
        return False


if __name__ == "__main__":
    if parse_and_save_rates():
        print(f"Данные успешно сохранены в {OUTPUT_FILE}")
    else:
        print("Не удалось спарсить данные. Проверьте логи в parser.log")