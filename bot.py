import logging
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import aiohttp
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import List, Optional, Tuple

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = "8259524911:AAGMNvc6lYbTHcPlpjIfAxH80SI2tSPS9a0"

@dataclass
class UserSettings:
    """Хранение настроек пользователя"""
    categories: List[str] = None
    keywords: List[str] = None
    min_price: float = 0
    max_price: float = float('inf')
    
    def __post_init__(self):
        if self.categories is None:
            self.categories = []
        if self.keywords is None:
            self.keywords = []

# Хранилище настроек пользователей
user_settings = {}

def extract_price(price_text: str) -> Optional[float]:
    """Извлечение числа из строки с ценой"""
    if not price_text:
        return None
    
    # Ищем числа с разделителями (1,000.50 или 1 000,50)
    price_text = price_text.replace(',', '.').replace(' ', '')
    
    # Ищем все числа в тексте
    matches = re.findall(r'[\d]+[.,\d]*', price_text)
    if not matches:
        return None
    
    # Берем первое найденное число
    try:
        # Убираем все нецифровые символы кроме точки
        clean_price = re.sub(r'[^\d.]', '', matches[0])
        return float(clean_price)
    except:
        return None

async def handle_category_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ссылки на категорию"""
    user_id = update.effective_user.id
    url = update.message.text.strip()
    
    # Проверяем, что ссылка от FunPay
    if 'funpay.com' not in url:
        await update.message.reply_text("❌ Пожалуйста, отправьте ссылку на категорию FunPay")
        return
    
    # Инициализируем настройки пользователя, если их нет
    if user_id not in user_settings:
        user_settings[user_id] = UserSettings()
    
    # Добавляем категорию
    if url not in user_settings[user_id].categories:
        user_settings[user_id].categories.append(url)
        await update.message.reply_text(
            f"✅ Категория добавлена!\n"
            f"📁 Ссылка: {url}\n\n"
            f"Теперь настройте фильтры:\n"
            f"1. /keywords - ключевые слова\n"
            f"2. /price - диапазон цен"
        )
    else:
        await update.message.reply_text("ℹ️ Эта категория уже добавлена")

async def set_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка ключевых слов для поиска в названии"""
    user_id = update.effective_user.id
    
    if user_id not in user_settings:
        user_settings[user_id] = UserSettings()
    
    if not context.args:
        await update.message.reply_text(
            "📝 Укажите ключевые слова для поиска **в названии лота**:\n\n"
            "Примеры:\n"
            "/keywords аккаунт steam, кс го, скин нож\n"
            "/keywords голда, валюта, золото\n"
            "/keywords brainrot, pet, rare"
        )
        return
    
    # Обрабатываем ключевые слова
    keywords_input = ' '.join(context.args)
    keywords = [kw.strip().lower() for kw in keywords_input.split(',') if kw.strip()]
    
    if not keywords:
        await update.message.reply_text("❌ Не указаны ключевые слова")
        return
    
    user_settings[user_id].keywords = keywords
    
    await update.message.reply_text(
        f"✅ Ключевые слова сохранены ({len(keywords)}):\n\n" +
        '\n'.join([f"• `{kw}`" for kw in keywords]) +
        f"\n\n📊 Фильтр: название лота должно содержать любое из этих слов\n"
        f"💰 Диапазон цен: {user_settings[user_id].min_price} - {user_settings[user_id].max_price if user_settings[user_id].max_price != float('inf') else '∞'} ₽\n\n"
        f"Используйте /price для настройки цены\n"
        f"Используйте /find для поиска"
    , parse_mode='Markdown')

async def set_price_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка диапазона цен"""
    user_id = update.effective_user.id
    
    if user_id not in user_settings:
        user_settings[user_id] = UserSettings()
    
    if not context.args:
        await update.message.reply_text(
            "💰 Укажите диапазон цен:\n\n"
            "Примеры:\n"
            "/price 100 1000 - от 100 до 1000 ₽\n"
            "/price 0 500 - до 500 ₽\n"
            "/price 1000 0 - от 1000 ₽ (без верхнего предела)\n"
            "/price reset - сбросить фильтр цены"
        )
        return
    
    # Обработка команды сброса
    if context.args[0].lower() == 'reset':
        user_settings[user_id].min_price = 0
        user_settings[user_id].max_price = float('inf')
        await update.message.reply_text("✅ Фильтр цены сброшен")
        return
    
    # Парсинг диапазона цен
    try:
        if len(context.args) == 1:
            # Только максимальная цена
            max_price = float(context.args[0])
            user_settings[user_id].min_price = 0
            user_settings[user_id].max_price = max_price
        elif len(context.args) >= 2:
            # Минимальная и максимальная цена
            min_price = float(context.args[0])
            max_price = float(context.args[1])
            
            if max_price == 0:
                max_price = float('inf')
            
            if min_price > max_price and max_price != float('inf'):
                await update.message.reply_text("❌ Минимальная цена не может быть больше максимальной")
                return
            
            user_settings[user_id].min_price = min_price
            user_settings[user_id].max_price = max_price
        
        # Форматируем вывод максимальной цены
        max_price_display = user_settings[user_id].max_price
        if max_price_display == float('inf'):
            max_price_display = '∞'
        
        await update.message.reply_text(
            f"✅ Диапазон цен установлен:\n"
            f"💰 От {user_settings[user_id].min_price} до {max_price_display} ₽\n\n"
            f"📝 Ключевые слова: {', '.join(user_settings[user_id].keywords) if user_settings[user_id].keywords else 'не заданы'}\n"
            f"📁 Категорий: {len(user_settings[user_id].categories)}\n\n"
            f"Используйте /find для поиска"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, укажите числа для цен")

async def parse_funpay_category(url: str, user_setting: UserSettings) -> List[dict]:
    """Парсинг категории FunPay с фильтрацией"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
    }
    
    found_lots = []
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Ошибка {response.status} для {url}")
                    return found_lots
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # === ВАЖНО: Нужно исследовать структуру конкретной категории ===
                # Примерные селекторы - нужно уточнить для каждой категории
                
                # 1. Ищем контейнеры с лотами
                # На FunPay это могут быть элементы с классами:
                # - 'tc-item' (trading card item)
                # - 'lot-item'
                # - 'item' и т.д.
                
                lot_containers = soup.find_all('div', class_='tc-item')
                
                # Если не нашли по этому классу, пробуем другие варианты
                if not lot_containers:
                    lot_containers = soup.find_all('a', class_='tc-item')
                if not lot_containers:
                    lot_containers = soup.find_all('div', class_='lot-item')
                if not lot_containers:
                    # Последняя попытка: ищем любые элементы, которые выглядят как лоты
                    lot_containers = soup.find_all('div', class_=lambda x: x and ('item' in x or 'lot' in x))
                
                logger.info(f"Найдено {len(lot_containers)} контейнеров на {url}")
                
                for container in lot_containers[:50]:  # Ограничим для скорости
                    try:
                        # === ИЗВЛЕКАЕМ НАЗВАНИЕ ЛОТА ===
                        # Пробуем разные селекторы для названия
                        title_selectors = [
                            ('div', 'tc-desc-text'),
                            ('div', 'item-title'),
                            ('div', 'title'),
                            ('span', 'item-name'),
                            ('h5', None),  # Любой h5
                            ('h4', None),  # Любой h4
                            ('a', 'item-link')
                        ]
                        
                        lot_title = None
                        for tag, class_name in title_selectors:
                            if class_name:
                                elem = container.find(tag, class_=class_name)
                            else:
                                elem = container.find(tag)
                            
                            if elem and elem.text.strip():
                                lot_title = elem.text.strip()
                                break
                        
                        # Если не нашли специальным селектором, берем первый значимый текст
                        if not lot_title:
                            # Пробуем получить весь текст и взять первую осмысленную строку
                            all_text = container.get_text('\n', strip=True)
                            lines = [line for line in all_text.split('\n') if line and len(line) > 5]
                            if lines:
                                lot_title = lines[0]
                            else:
                                lot_title = all_text[:100]
                        
                        # === ИЗВЛЕКАЕМ ЦЕНУ ===
                        price_selectors = [
                            ('div', 'tc-price'),
                            ('div', 'price'),
                            ('span', 'price'),
                            ('div', 'item-price'),
                            ('b', None)  # Часто цена в <b>
                        ]
                        
                        price_text = None
                        for tag, class_name in price_selectors:
                            if class_name:
                                elem = container.find(tag, class_=class_name)
                            else:
                                elem = container.find(tag)
                            
                            if elem and elem.text.strip():
                                price_text = elem.text.strip()
                                break
                        
                        # Если не нашли, ищем текст с символами валюты
                        if not price_text:
                            price_elems = container.find_all(text=re.compile(r'[₽$€£]|\d+\s*(р|rub|руб)'))
                            if price_elems:
                                price_text = price_elems[0].strip()
                        
                        # === ИЗВЛЕКАЕМ ССЫЛКУ ===
                        link_elem = container.find('a', href=True)
                        if not link_elem and container.name == 'a':
                            link_elem = container
                        
                        lot_link = link_elem['href'] if link_elem and 'href' in link_elem.attrs else None
                        if lot_link and not lot_link.startswith('http'):
                            lot_link = f"https://funpay.com{lot_link}"
                        
                        # === ПРИМЕНЯЕМ ФИЛЬТРЫ ===
                        if not lot_title or not lot_link:
                            continue
                        
                        # 1. Фильтр по ключевым словам в названии
                        title_lower = lot_title.lower()
                        keyword_match = False
                        matched_keyword = None
                        
                        for keyword in user_setting.keywords:
                            if keyword.lower() in title_lower:
                                keyword_match = True
                                matched_keyword = keyword
                                break
                        
                        if not keyword_match:
                            continue
                        
                        # 2. Фильтр по цене
                        price_value = extract_price(price_text) if price_text else None
                        
                        if price_value is not None:
                            # Проверяем диапазон цен
                            if price_value < user_setting.min_price:
                                continue
                            if user_setting.max_price != float('inf') and price_value > user_setting.max_price:
                                continue
                        
                        # === ФОРМИРУЕМ РЕЗУЛЬТАТ ===
                        found_lots.append({
                            'title': lot_title[:150] + "..." if len(lot_title) > 150 else lot_title,
                            'link': lot_link,
                            'price_text': price_text or "Цена не указана",
                            'price_value': price_value,
                            'keyword': matched_keyword,
                            'category': url
                        })
                        
                    except Exception as e:
                        logger.debug(f"Ошибка парсинга лота: {e}")
                        continue
                
    except Exception as e:
        logger.error(f"Ошибка парсинга категории {url}: {e}")
    
    return found_lots

async def find_lots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск лотов по сохраненным настройкам"""
    user_id = update.effective_user.id
    
    if user_id not in user_settings:
        await update.message.reply_text("❌ Сначала настройте бота:\n1. Отправьте ссылку на категорию\n2. /keywords - ключевые слова\n3. /price - диапазон цен")
        return
    
    settings = user_settings[user_id]
    
    if not settings.categories:
        await update.message.reply_text("❌ Нет добавленных категорий")
        return
    
    if not settings.keywords:
        await update.message.reply_text("❌ Не заданы ключевые слова. Используйте /keywords")
        return
    
    await update.message.reply_text(
        f"🔍 Начинаю поиск...\n\n"
        f"📝 Ключевые слова: {', '.join(settings.keywords)}\n"
        f"💰 Диапазон цен: {settings.min_price} - {settings.max_price if settings.max_price != float('inf') else '∞'} ₽\n"
        f"📁 Категорий: {len(settings.categories)}"
    )
    
    all_found = []
    
    # Парсим каждую категорию
    for url in settings.categories:
        found = await parse_funpay_category(url, settings)
        all_found.extend(found)
    
    # Сортируем по цене (если есть)
    all_found.sort(key=lambda x: x['price_value'] or float('inf'))
    
    # Отправляем результаты
    if all_found:
        message = f"✅ **Найдено {len(all_found)} лотов:**\n\n"
        
        for i, lot in enumerate(all_found[:10], 1):  # Ограничиваем вывод 10 лотами
            price_display = f"{lot['price_value']} ₽" if lot['price_value'] else lot['price_text']
            
            message += f"**{i}. {lot['keyword']}** - {price_display}\n"
            message += f"📌 {lot['title']}\n"
            message += f"🔗 [Открыть лот]({lot['link']})\n"
            message += f"📁 {lot['category'].split('/')[-2] if '/' in lot['category'] else 'Категория'}\n"
            message += "―\n"
        
        if len(all_found) > 10:
            message += f"\n... и еще {len(all_found) - 10} лотов"
        
        await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)
    else:
        await update.message.reply_text(
            "❌ По вашим критериям ничего не найдено.\n\n"
            "Попробуйте:\n"
            "• Расширить диапазон цен /price\n"
            "• Добавить больше ключевых слов /keywords\n"
            "• Проверить другие категории"
        )

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать текущие настройки"""
    user_id = update.effective_user.id
    
    if user_id not in user_settings or (not user_settings[user_id].categories and not user_settings[user_id].keywords):
        await update.message.reply_text("⚙️ Настройки не заданы")
        return
    
    settings = user_settings[user_id]
    
    message = "⚙️ **Ваши настройки:**\n\n"
    
    if settings.keywords:
        message += f"📝 **Ключевые слова ({len(settings.keywords)}):**\n"
        message += ', '.join([f'`{kw}`' for kw in settings.keywords]) + "\n\n"
    
    max_price_display = settings.max_price if settings.max_price != float('inf') else '∞'
    message += f"💰 **Диапазон цен:** {settings.min_price} - {max_price_display} ₽\n\n"
    
    if settings.categories:
        message += f"📁 **Категории ({len(settings.categories)}):**\n"
        for i, url in enumerate(settings.categories[:3], 1):
            # Извлекаем название категории из URL
            category_name = url.split('/')[-2] if '/' in url else url[:30]
            message += f"{i}. {category_name}\n"
        
        if len(settings.categories) > 3:
            message += f"... и еще {len(settings.categories) - 3}\n"
    
    message += "\n🛠 **Команды:**\n"
    message += "/find - начать поиск\n"
    message += "/keywords - изменить ключевые слова\n"
    message += "/price - изменить диапазон цен\n"
    message += "/clear - очистить все настройки"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def clear_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистить все настройки"""
    user_id = update.effective_user.id
    
    if user_id in user_settings:
        del user_settings[user_id]
    
    await update.message.reply_text("✅ Все настройки очищены")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Справка по использованию"""
    help_text = """
🤖 **FunPay Парсер - Помощь**

📌 **Как начать:**
1. Отправьте боту ссылку на категорию FunPay
2. Задайте ключевые слова: `/keywords аккаунт, скин, ксго`
3. Установите диапазон цен: `/price 100 1000`
4. Найдите лоты: `/find`

🛠 **Основные команды:**
• `/keywords` - ключевые слова в названии лота
• `/price` - минимальная и максимальная цена
• `/find` - начать поиск по критериям
• `/settings` - текущие настройки
• `/clear` - очистить все настройки

🔍 **Примеры категорий FunPay:**
• Аккаунты Steam
• Скины CS2/CS:GO
• Игровая валюта
• Промо-коды

💡 **Советы:**
• Используйте несколько ключевых слов через запятую
• Цены можно указывать как "100 5000" или "0 1000"
• Для ссылок: нажмите "Поделиться" на странице категории
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

def main():
    """Запуск бота"""
    application = Application.builder().token(TOKEN).build()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", help_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("keywords", set_keywords))
    application.add_handler(CommandHandler("price", set_price_range))
    application.add_handler(CommandHandler("find", find_lots))
    application.add_handler(CommandHandler("settings", show_settings))
    application.add_handler(CommandHandler("clear", clear_settings))
    
    # Обработчик ссылок на категории
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'funpay\.com'),
        handle_category_link
    ))
    
    logger.info("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()
