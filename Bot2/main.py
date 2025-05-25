import telebot
from telebot import types
import requests
import json
from datetime import datetime
import time
import threading
import logging
import math
from math import radians, sin, cos, sqrt, atan2

# Настройка логирования
logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Инициализация бота
bot = telebot.TeleBot('7285252427:AAEbH8M65QdLdeogC0kQ602b7siHToORSvs')  # Замените на ваш токен

# Конфигурация API
NBRB_API_URL = 'https://api.nbrb.by/exrates/rates?periodicity=0'  # API НБРБ для традиционных валют
BINANCE_API_URL = 'https://api.binance.com/api/v3/ticker/price'  # API Binance для криптовалют
BINANCE_CONVERT_URL = 'https://api.binance.com/api/v3/ticker/price?symbol='  # Для конверсии криптовалют
YANDEX_MAPS_URL = 'https://yandex.com/maps/?rtext='  # Базовый URL для Яндекс.Карт
YANDEX_SEARCH_URL = 'https://yandex.com/maps/?text='  # URL для поиска по улице

# Список валют
FIAT_CURRENCIES = ['USD', 'EUR', 'CNY']  # Валюты для курса НБРБ
CRYPTO_CURRENCIES = ['BTC', 'ETH', 'BNB', 'XRP', 'ADA']  # Список из 5 криптовалют

# Хранилища данных
subscriptions = {}
last_fiat_rates = {}
last_crypto_rates = {}
last_fiat_update_time = 0
last_crypto_update_time = 0
CACHE_DURATION = 3600  # 1 час

# Функция для вычисления расстояния между двумя точками (Haversine)
def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371  # Радиус Земли в километрах
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    distance = R * c
    return distance

# Функция для извлечения улицы из адреса
def extract_street(address):
    # Упрощенная логика: берем часть после первой запятой и до номера дома (если есть)
    parts = address.split(', ')
    if len(parts) > 1:
        street_part = parts[1].split(' ')[0]  # Берем первое слово после запятой как улицу
        return street_part
    return address.replace('г. Минск, ', '').split(' ')[0]  # Если запятой нет, берем первое слово

# Функция для получения курсов традиционных валют с НБРБ
def get_fiat_rates():
    global last_fiat_rates, last_fiat_update_time
    current_time = time.time()

    if last_fiat_rates and (current_time - last_fiat_update_time) < CACHE_DURATION:
        logging.info("Используем кэшированные данные для традиционных валют")
        return last_fiat_rates

    try:
        response = requests.get(NBRB_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        fiat_rates = {}
        for item in data:
            if item['Cur_Abbreviation'] in FIAT_CURRENCIES:
                fiat_rates[item['Cur_Abbreviation']] = {
                    'rate': item['Cur_OfficialRate'],
                    'scale': item['Cur_Scale']
                }
        last_fiat_rates = fiat_rates
        last_fiat_update_time = current_time
        logging.info("Успешно получены курсы традиционных валют")
        return fiat_rates
    except requests.RequestException as e:
        logging.error(f"Ошибка при получении курсов НБРБ: {e}")
        return last_fiat_rates if last_fiat_rates else {}

# Функция для получения курсов криптовалют с Binance
def get_crypto_rates():
    global last_crypto_rates, last_crypto_update_time
    current_time = time.time()

    if last_crypto_rates and (current_time - last_crypto_update_time) < CACHE_DURATION:
        logging.info("Используем кэшированные данные для криптовалют")
        return last_crypto_rates

    try:
        response = requests.get(BINANCE_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        crypto_rates = {}
        for crypto in CRYPTO_CURRENCIES:
            symbol = f"{crypto}USDT"
            for item in data:
                if item['symbol'] == symbol:
                    usd_rate = float(item['price'])
                    fiat_rates = get_fiat_rates()
                    usd_to_byn = fiat_rates.get('USD', {}).get('rate', None)
                    scale_usd = fiat_rates.get('USD', {}).get('scale', 1)
                    if usd_to_byn:
                        byn_rate = usd_rate * (usd_to_byn / scale_usd)
                    else:
                        byn_rate = None
                    crypto_rates[crypto] = {
                        'USD': usd_rate,
                        'BYN': byn_rate
                    }
                    break
        last_crypto_rates = crypto_rates
        last_crypto_update_time = current_time
        logging.info("Успешно получены курсы криптовалют")
        return crypto_rates
    except requests.RequestException as e:
        logging.error(f"Ошибка при получении курсов криптовалют: {e}")
        return last_crypto_rates if last_crypto_rates else {}

# Функция для конверсии криптовалют через Binance
def convert_crypto(amount, from_currency, to_currency):
    try:
        if from_currency in FIAT_CURRENCIES or to_currency in FIAT_CURRENCIES:
            crypto = from_currency if from_currency in CRYPTO_CURRENCIES else to_currency
            fiat = to_currency if to_currency in FIAT_CURRENCIES else from_currency
            crypto_rates = get_crypto_rates()
            if crypto not in crypto_rates:
                return None
            if fiat == 'USD':
                rate = crypto_rates[crypto]['USD']
            else:
                rate = crypto_rates[crypto]['BYN']
                if rate is None:
                    return None
            if from_currency in CRYPTO_CURRENCIES:
                return amount * rate
            else:
                return amount / rate if rate != 0 else None
        else:
            symbol = f"{from_currency}{to_currency}"
            response = requests.get(f"{BINANCE_CONVERT_URL}{symbol}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                rate = float(data['price'])
                return amount * rate
            symbol1 = f"{from_currency}USDT"
            symbol2 = f"{to_currency}USDT"
            response1 = requests.get(f"{BINANCE_CONVERT_URL}{symbol1}", timeout=10)
            response2 = requests.get(f"{BINANCE_CONVERT_URL}{symbol2}", timeout=10)
            if response1.status_code == 200 and response2.status_code == 200:
                rate1 = float(response1.json()['price'])
                rate2 = float(response2.json()['price'])
                if rate2 != 0:
                    return amount * (rate1 / rate2)
            return None
    except requests.RequestException as e:
        logging.error(f"Ошибка при конверсии криптовалют: {e}")
        return None
    except Exception as e:
        logging.error(f"Общая ошибка при конверсии: {e}")
        return None

# Функция для чтения лучших курсов из JSON
def get_best_rates():
    try:
        with open('bank_rates.json', 'r', encoding='utf-8') as f:
            rates = json.load(f)

        # Добавляем курс НБРБ
        fiat_rates = get_fiat_rates()
        usd_nbrb = fiat_rates.get('USD', {}).get('rate', 0.0)
        eur_nbrb = fiat_rates.get('EUR', {}).get('rate', 0.0)

        for rate in rates:
            rate['USD']['nbrb'] = usd_nbrb
            rate['EUR']['nbrb'] = eur_nbrb

        logging.info("Курсы успешно загружены из bank_rates.json")
        return rates
    except FileNotFoundError:
        logging.error("Файл bank_rates.json не найден")
        return []
    except Exception as e:
        logging.error(f"Ошибка при чтении bank_rates.json: {e}")
        return []

# Создание основного меню
def create_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("₿ Курс криптовалют")
    btn2 = types.KeyboardButton("📈 Курс валют")
    btn3 = types.KeyboardButton("🏦 Лучшие курсы")
    markup.add(btn1, btn2, btn3)
    return markup

# Создание подменю для "Лучшие курсы"
def create_best_rates_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    btn1 = types.KeyboardButton("Сортировать")
    btn2 = types.KeyboardButton("Топ-3 курсов")
    btn3 = types.KeyboardButton("Назад")
    markup.add(btn1, btn2, btn3)
    return markup

# Создание меню для сортировки
def create_sort_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    btn1 = types.KeyboardButton("Сортировать по USD (Покупка)")
    btn2 = types.KeyboardButton("Сортировать по USD (Продажа)")
    btn3 = types.KeyboardButton("Сортировать по EUR (Покупка)")
    btn4 = types.KeyboardButton("Сортировать по EUR (Продажа)")
    btn5 = types.KeyboardButton("Назад")
    markup.add(btn1, btn2, btn3, btn4, btn5)
    return markup

# Создание меню для выбора топ-3
def create_top_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    btn1 = types.KeyboardButton("1-е место")
    btn2 = types.KeyboardButton("2-е место")
    btn3 = types.KeyboardButton("3-е место")
    btn4 = types.KeyboardButton("Ближайшие (3 км)")
    btn5 = types.KeyboardButton("Назад")
    markup.add(btn1, btn2, btn3, btn4, btn5)
    return markup

# Команда /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message,
                 "Добро пожаловать! Я бот для отслеживания курсов валют.\n"
                 "Используйте кнопки ниже для работы со мной.",
                 reply_markup=create_main_menu())

# Проверка лучших курсов
@bot.message_handler(func=lambda message: message.text == "🏦 Лучшие курсы")
def check_best_rates(message):
    bot.reply_to(message, "Выберите действие:", reply_markup=create_best_rates_menu())

# Обработка выбора действия в подменю "Лучшие курсы"
@bot.message_handler(func=lambda message: message.text in ["Сортировать", "Топ-3 курсов", "Назад"])
def handle_best_rates_action(message):
    if message.text == "Назад":
        bot.reply_to(message, "Возвращаюсь в главное меню.", reply_markup=create_main_menu())
        return
    elif message.text == "Сортировать":
        markup = create_sort_menu()
        bot.reply_to(message, "Выберите способ сортировки:", reply_markup=markup)
    elif message.text == "Топ-3 курсов":
        best_rates = get_best_rates()
        if not best_rates:
            bot.reply_to(message, "Не удалось загрузить курсы из файла. Убедитесь, что bank_rates.json существует.", reply_markup=create_main_menu())
            return

        # Сортируем по покупке USD
        best_rates.sort(key=lambda x: x['USD']['buy'], reverse=True)
        top_3 = best_rates[:3]

        response = "🏦 Лучшие курсы в Минске (по данным Myfin.by):\n\n"
        for i, rate in enumerate(top_3, 1):
            response += f"{i}-е место: 🏦 {rate['bank']}\n"
            response += f"💵 USD: Покупка: {rate['USD']['buy']:.2f}, Продажа: {rate['USD']['sell']:.2f}, НБРБ: {rate['USD']['nbrb']:.2f}\n"
            response += f"💶 EUR: Покупка: {rate['EUR']['buy']:.2f}, Продажа: {rate['EUR']['sell']:.2f}, НБРБ: {rate['EUR']['nbrb']:.2f}\n"
            response += "📍 Отделения:\n"
            for branch in rate.get('branches', []):
                response += f"- {branch['address']}\n"
            response += "\n"

        # Разбиваем сообщение, если слишком длинное
        if len(response) > 4000:
            for i in range(0, len(response), 4000):
                bot.reply_to(message, response[i:i+4000], reply_markup=create_top_menu() if i == 0 else None)
        else:
            bot.reply_to(message, response, reply_markup=create_top_menu())

# Обработка сортировки (все банки)
@bot.message_handler(func=lambda message: message.text in [
    "Сортировать по USD (Покупка)", "Сортировать по USD (Продажа)",
    "Сортировать по EUR (Покупка)", "Сортировать по EUR (Продажа)", "Назад"
])
def handle_best_rates_sort(message):
    if message.text == "Назад":
        bot.reply_to(message, "Возвращаюсь в меню выбора.", reply_markup=create_best_rates_menu())
        return

    best_rates = get_best_rates()
    if not best_rates:
        bot.reply_to(message, "Не удалось загрузить курсы из файла. Убедитесь, что bank_rates.json существует.", reply_markup=create_main_menu())
        return

    # Фильтруем и сортируем только по курсам
    if message.text == "Сортировать по USD (Покупка)":
        best_rates.sort(key=lambda x: x['USD']['buy'], reverse=True)
    elif message.text == "Сортировать по USD (Продажа)":
        best_rates.sort(key=lambda x: x['USD']['sell'], reverse=True)
    elif message.text == "Сортировать по EUR (Покупка)":
        best_rates.sort(key=lambda x: x['EUR']['buy'], reverse=True)
    elif message.text == "Сортировать по EUR (Продажа)":
        best_rates.sort(key=lambda x: x['EUR']['sell'], reverse=True)

    # Формируем ответ
    response = "🏦 Лучшие курсы в Минске (по данным Myfin.by):\n\n"
    for rate in best_rates:
        new_response = f"🏦 Банк: {rate['bank']}\n"
        new_response += f"💵 USD: Покупка: {rate['USD']['buy']:.2f}, Продажа: {rate['USD']['sell']:.2f}, НБРБ: {rate['USD']['nbrb']:.2f}\n"
        new_response += f"💶 EUR: Покупка: {rate['EUR']['buy']:.2f}, Продажа: {rate['EUR']['sell']:.2f}, НБРБ: {rate['EUR']['nbrb']:.2f}\n"
        new_response += "📍 Отделения:\n"
        for branch in rate.get('branches', []):
            new_response += f"- {branch['address']}\n"
        new_response += "\n"

        if len(response) + len(new_response) > 4000:
            bot.reply_to(message, response, reply_markup=create_best_rates_menu())
            response = new_response
        else:
            response += new_response

    if response.strip():
        bot.reply_to(message, response, reply_markup=create_best_rates_menu())

# Обработка выбора топ-3 или ближайших
@bot.message_handler(func=lambda message: message.text in ["1-е место", "2-е место", "3-е место", "Ближайшие (3 км)", "Назад"])
def handle_top_selection(message):
    if message.text == "Назад":
        bot.reply_to(message, "Возвращаюсь в меню выбора.", reply_markup=create_best_rates_menu())
        return

    best_rates = get_best_rates()
    if not best_rates:
        bot.reply_to(message, "Не удалось загрузить курсы из файла.", reply_markup=create_main_menu())
        return

    # Сортируем по покупке USD
    best_rates.sort(key=lambda x: x['USD']['buy'], reverse=True)
    top_3 = best_rates[:3]

    if message.text == "Ближайшие (3 км)":
        # Запрос геолокации
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        btn = types.KeyboardButton("Отправить местоположение", request_location=True)
        btn_back = types.KeyboardButton("Назад")
        markup.add(btn, btn_back)
        bot.reply_to(message, "Пожалуйста, отправьте ваше местоположение для поиска ближайших отделений:", reply_markup=markup)
        bot.register_next_step_handler(message, lambda m: process_location(m, top_3))
        return

    # Обработка выбора 1-е, 2-е или 3-е место
    place = {"1-е место": 0, "2-е место": 1, "3-е место": 2}[message.text]
    bank = top_3[place]

    bank_name = bank['bank']
    branches = bank.get('branches', [])
    response = f"🏦 {bank_name}\n"
    response += f"💵 USD: Покупка: {bank['USD']['buy']:.2f}, Продажа: {bank['USD']['sell']:.2f}, НБРБ: {bank['USD']['nbrb']:.2f}\n"
    response += f"💶 EUR: Покупка: {bank['EUR']['buy']:.2f}, Продажа: {bank['EUR']['sell']:.2f}, НБРБ: {bank['EUR']['nbrb']:.2f}\n\n"
    response += "📍 Отделения и маршруты:\n"

    for branch in branches:
        lat, lon = branch.get('coords', (0, 0))  # Используем (0, 0) как заглушку, если координаты отсутствуют
        if lat == 0 and lon == 0:
            street = extract_street(branch['address'])
            yandex_search_link = f"{YANDEX_SEARCH_URL}{street.replace(' ', '+')}"
            response += f"- {branch['address']} (координаты отсутствуют, поиск по улице)\n"
            response += f"  1. Поиск: [Нажмите здесь]({yandex_search_link})\n"
        else:
            yandex_link = f"{YANDEX_MAPS_URL}{lat},{lon}~53.9025,27.5616"
            response += f"- {branch['address']}\n"
            response += f"  1. Пешком: [Нажмите здесь]({yandex_link}&mode=walking)\n"
            response += f"  2. На транспорте: [Нажмите здесь]({yandex_link}&mode=transit)\n"
            response += f"  3. На машине: [Нажмите здесь]({yandex_link}&mode=driving)\n\n"

    # Разбиваем сообщение, если слишком длинное
    if len(response) > 4000:
        for i in range(0, len(response), 4000):
            bot.reply_to(message, response[i:i+4000], reply_markup=create_best_rates_menu() if i == 0 else None)
    else:
        bot.reply_to(message, response, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=create_best_rates_menu())

# Обработка геолокации
def process_location(message, top_3):
    if message.text == "Назад":
        bot.reply_to(message, "Возвращаюсь в меню выбора.", reply_markup=create_best_rates_menu())
        return

    if message.location:
        user_lat = message.location.latitude
        user_lon = message.location.longitude

        # Поиск ближайших отделений из топ-3 в радиусе 3 км
        response = "🏦 Ближайшие отделения из топ-3 в радиусе 3 км:\n\n"
        has_nearby = False
        for bank in top_3:
            bank_name = bank['bank']
            branches = bank.get('branches', [])
            for branch in branches:
                lat, lon = branch.get('coords', (user_lat, user_lon))  # Используем координаты пользователя, если отсутствуют
                distance = haversine_distance(user_lat, user_lon, lat, lon)
                if distance <= 3:  # Радиус 3 км
                    has_nearby = True
                    response += f"🏦 {bank_name} - {branch['address']}\n"
                    response += f"  Расстояние: {distance:.2f} км\n"
                    if lat == user_lat and lon == user_lon:  # Если координаты отсутствуют
                        street = extract_street(branch['address'])
                        yandex_search_link = f"{YANDEX_SEARCH_URL}{street.replace(' ', '+')}"
                        response += f"  1. Поиск по улице: [Нажмите здесь]({yandex_search_link})\n"
                    else:
                        yandex_link = f"{YANDEX_MAPS_URL}{lat},{lon}~{user_lat},{user_lon}"
                        response += f"  1. Пешком: [Нажмите здесь]({yandex_link}&mode=walking)\n"
                        response += f"  2. На транспорте: [Нажмите здесь]({yandex_link}&mode=transit)\n"
                        response += f"  3. На машине: [Нажмите здесь]({yandex_link}&mode=driving)\n\n"

        if not has_nearby:
            response = "Нет отделений из топ-3 в радиусе 3 км от вашего местоположения."

        # Разбиваем сообщение, если слишком длинное
        if len(response) > 4000:
            for i in range(0, len(response), 4000):
                bot.reply_to(message, response[i:i+4000], reply_markup=create_best_rates_menu() if i == 0 else None)
        else:
            bot.reply_to(message, response, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=create_best_rates_menu())
    else:
        bot.reply_to(message, "Пожалуйста, отправьте ваше местоположение.", reply_markup=create_best_rates_menu())

# Проверка курсов криптовалют
@bot.message_handler(func=lambda message: message.text == "₿ Курс криптовалют")
def check_crypto_rates(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    btn1 = types.KeyboardButton("Посмотреть курсы")
    btn2 = types.KeyboardButton("Конвертировать криптовалюту")
    btn3 = types.KeyboardButton("Назад")
    markup.add(btn1, btn2, btn3)
    bot.reply_to(message, "Выберите действие:", reply_markup=markup)

# Обработка выбора действия для криптовалют
@bot.message_handler(func=lambda message: message.text in ["Посмотреть курсы", "Конвертировать криптовалюту", "Назад"])
def handle_crypto_action(message):
    if message.text == "Назад":
        bot.reply_to(message, "Возвращаюсь в главное меню.", reply_markup=create_main_menu())
        return
    elif message.text == "Посмотреть курсы":
        crypto_rates = get_crypto_rates()
        if not crypto_rates:
            bot.reply_to(message, "Не удалось получить курсы криптовалют. Попробуйте позже.", reply_markup=create_main_menu())
            return
        response = "Курсы криптовалют:\n\n"
        for crypto in CRYPTO_CURRENCIES:
            if crypto in crypto_rates:
                usd_rate = crypto_rates[crypto]['USD']
                byn_rate = crypto_rates[crypto]['BYN']
                response += f"{crypto}:\n"
                response += f"  USD: {usd_rate:,.2f}\n"
                response += f"  BYN: {byn_rate:,.2f}\n" if byn_rate is not None else "  BYN: Ошибка данных\n"
                response += "\n"
            else:
                response += f"{crypto}: Ошибка данных\n\n"
        bot.reply_to(message, response, reply_markup=create_main_menu())
    elif message.text == "Конвертировать криптовалюту":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        buttons = [types.KeyboardButton(c) for c in CRYPTO_CURRENCIES + ['USD', 'BYN']]
        markup.add(*buttons)
        bot.reply_to(message, "Выберите валюту, из которой конвертировать:", reply_markup=markup)
        bot.register_next_step_handler(message, select_from_currency)

# Проверка курсов традиционных валют
@bot.message_handler(func=lambda message: message.text == "📈 Курс валют")
def check_fiat_rates(message):
    fiat_rates = get_fiat_rates()
    if not fiat_rates:
        bot.reply_to(message, "Не удалось получить курсы валют. Попробуйте позже.", reply_markup=create_main_menu())
        return
    response = "Курсы валют к BYN (по данным НБРБ):\n\n"
    for currency in FIAT_CURRENCIES:
        if currency in fiat_rates:
            rate = fiat_rates[currency]['rate']
            scale = fiat_rates[currency]['scale']
            response += f"{scale} {currency} = {rate:.2f} BYN\n"
        else:
            response += f"{currency}: Ошибка данных\n"
    bot.reply_to(message, response, reply_markup=create_main_menu())

# Выбор валюты для конверсии
def select_from_currency(message):
    from_currency = message.text
    if from_currency not in (CRYPTO_CURRENCIES + ['USD', 'BYN']):
        bot.reply_to(message, "Неверная валюта!", reply_markup=create_main_menu())
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    buttons = [types.KeyboardButton(c) for c in CRYPTO_CURRENCIES + ['USD', 'BYN']]
    markup.add(*buttons)
    bot.reply_to(message, "Выберите валюту, в которую конвертировать:", reply_markup=markup)
    bot.register_next_step_handler(message, lambda m: select_to_currency(m, from_currency))

def select_to_currency(message, from_currency):
    to_currency = message.text
    if to_currency not in (CRYPTO_CURRENCIES + ['USD', 'BYN']):
        bot.reply_to(message, "Неверная валюта!", reply_markup=create_main_menu())
        return
    bot.reply_to(message, "Введите сумму для конвертации:")
    bot.register_next_step_handler(message, lambda m: process_conversion(m, from_currency, to_currency))

def process_conversion(message, from_currency, to_currency):
    try:
        amount = float(message.text)
        result = convert_crypto(amount, from_currency, to_currency)
        if result:
            bot.reply_to(message, f"{amount} {from_currency} = {result:.2f} {to_currency}",
                         reply_markup=create_main_menu())
        else:
            bot.reply_to(message, "Ошибка конверсии. Попробуйте позже.", reply_markup=create_main_menu())
    except ValueError:
        bot.reply_to(message, "Пожалуйста, введите числовое значение.", reply_markup=create_main_menu())

if __name__ == '__main__':
    logging.info("Бот запущен...")
    bot.polling(none_stop=True)