import asyncio
import logging
import re
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
    import aiohttp
    from bs4 import BeautifulSoup
    HAVE_ALL_DEPS = True
except ImportError as e:
    print(f"❌ Отсутствуют необходимые библиотеки: {e}")
    print("Установите их командой:")
    print("pip install python-telegram-bot aiohttp beautifulsoup4")
    HAVE_ALL_DEPS = False

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = "8259524911:AAGMNvc6lYbTHcPlpjIfAxH80SI2tSPS9a0"  # Замените на ваш токен

@dataclass
class UserSettings:
    """Хранение настроек пользователя"""
    categories: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    min_price: float = 0
    max_price: float = float('inf')
    monitored_lots: Dict[str, datetime] = field(default_factory=dict)

# Хранилище настроек пользователей
user_settings: Dict[int, UserSettings] = {}

def extract_price(price_text: str) -> Optional[float]:
    """Извлечение числа из строки с ценой"""
    if not price_text:
        return None
    
    # Нормализуем строку
    price_text = price_text.replace(',', '.').replace(' ', '').replace('\xa0', '')
    
    # Ищем числа
    matches = re.findall(r'[\d]+\.?[\d]*', price_text)
    if not matches:
        return None
    
    try:
        return float(matches[0])
    except ValueError:
        return None

def validate_funpay_url(url: str) -> bool:
    """Проверка, что ссылка ведет на FunPay"""
    return 'funpay.com' in url and ('/lots/' in url or '/chips/' in url)

async def send_error_message(update: Update, error_msg: str):
    """Отправка сообщения об ошибке"""
    if update and update.message:
        await update.message.reply_text(f"❌ {error_msg}")

async def handle_category_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ссылки на категорию"""
    if not HAVE_ALL_DEPS:
        await send_error_message(update, "Библиотеки не установлены. См. инструкцию по установке.")
        return
    
    user_id = update.effective_user.id
    url = update.message.text.strip()
    
    if not validate_funpay_url(url):
        await update.message.reply_text(
            "❌ Неверная ссылка. Отправьте ссылку на категорию FunPay.\n"
            "Пример: https://funpay.com/lots/123/"
        )
        return
    
    if user_id not in user_settings:
        user_settings[user_id] = UserSettings()
    
    if url not in user_settings[user_id].categories:
        user_settings[user_id].categories.append(url)
        await update.message.reply_text(
            f"✅ Категория добавлена!\n"
            f"📁 Ссылка: {url}\n\n"
            f"Теперь настройте фильтры:\n"
            f"1. /keywords - ключевые слова для поиска\n"
            f"2. /price - диапазон цен\n"
            f"3. /find - начать поиск"
        )
    else:
        await update.message.reply_text("ℹ️ Эта категория уже добавлена")

async def set_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка ключевых слов для поиска"""
    user_id = update.effective_user.id
    
    if user_id not in user_settings:
        user_settings[user_id] = UserSettings()
    
    if not context.args:
        await update.message.reply_text(
            "📝 **Укажите ключевые слова через запятую:**\n\n"
            "Примеры:\n"
            "`/keywords аккаунт, стим, скин`\n"
            "`/keywords голда, валюта, золото`\n"
            "`/keywords brainrot, pet, rare`\n\n"
            "⚠️ Бот будет искать эти слова в **названиях** лотов."
        , parse_mode='Markdown')
        return
    
    keywords_input = ' '.join(context.args)
    keywords = [kw.strip().lower() for kw in keywords_input.split(',') if kw.strip()]
    
    if not keywords:
        await update.message.reply_text("❌ Не указаны ключевые слова")
        return
    
    user_settings[user_id].keywords = keywords
    
    max_price = user_settings[user_id].max_price
    max_price_display = f"{max_price:.2f}" if max_price != float('inf') else "∞"
    
    await update.message.reply_text(
        f"✅ **Ключевые слова сохранены:**\n\n" +
        '\n'.join([f"• `{kw}`" for kw in keywords]) +
        f"\n\n**Фильтры:**\n"
        f"• 📝 Ключевых слов: {len(keywords)}\n"
        f"• 💰 Диапазон цен: {user_settings[user_id].min_price} - {max_price_display} ₽\n"
        f"• 📁 Категорий: {len(user_settings[user_id].categories)}\n\n"
        f"**Используйте:**\n"
        f"`/price` - изменить цену\n"
        f"`/find` - начать поиск\n"
        f"`/settings` - показать настройки"
    , parse_mode='Markdown')

async def set_price_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка диапазона цен"""
    user_id = update.effective_user.id
    
    if user_id not in user_settings:
        user_settings[user_id] = UserSettings()
    
    if not context.args:
        await update.message.reply_text(
            "💰 **Укажите диапазон цен:**\n\n"
            "**Примеры:**\n"
            "`/price 100 1000` - от 100 до 1000 ₽\n"
            "`/price 0 500` - до 500 ₽\n"
            "`/price 1000 0` - от 1000 ₽ (без верхнего предела)\n"
            "`/price reset` - сбросить фильтр цены"
        , parse_mode='Markdown')
        return
    
    if context.args[0].lower() == 'reset':
        user_settings[user_id].min_price = 0
        user_settings[user_id].max_price = float('inf')
        await update.message.reply_text("✅ Фильтр цены сброшен")
        return
    
    try:
        if len(context.args) == 1:
            max_price = float(context.args[0])
            user_settings[user_id].min_price = 0
            user_settings[user_id].max_price = max_price
        elif len(context.args) >= 2:
            min_price = float(context.args[0])
            max_price = float(context.args[1])
            
            if max_price == 0:
                max_price = float('inf')
            
            if min_price > max_price and max_price != float('inf'):
                await update.message.reply_text("❌ Минимальная цена не может быть больше максимальной")
                return
            
            user_settings[user_id].min_price = min_price
            user_settings[user_id].max_price = max_price
        
        max_price_display = user_settings[user_id].max_price
        if max_price_display == float('inf'):
            max_price_display = '∞'
        else:
            max_price_display = f"{max_price_display:.2f}"
        
        keywords_count = len(user_settings[user_id].keywords)
        categories_count = len(user_settings[user_id].categories)
        
        await update.message.reply_text(
            f"✅ **Диапазон цен установлен:**\n"
            f"💰 **От {user_settings[user_id].min_price} до {max_price_display} ₽**\n\n"
            f"📝 Ключевых слов: {keywords_count}\n"
            f"📁 Категорий: {categories_count}\n\n"
            f"**Используйте:**\n"
            f"`/find` - начать поиск лотов"
        , parse_mode='Markdown')
        
    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, укажите корректные числа для цен")

async def parse_funpay_category(url: str, settings: UserSettings) -> List[Dict[str, Any]]:
    """Парсинг категории FunPay"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    
    found_lots = []
    
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    logger.error(f"HTTP {response.status} для {url}")
                    return found_lots
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Поиск лотов - ВАЖНО: нужно адаптировать под конкретную структуру FunPay
                # Пробуем разные варианты селекторов
                selectors = [
                    {'tag': 'div', 'class': 'tc-item'},
                    {'tag': 'a', 'class': 'tc-item'},
                    {'tag': 'div', 'class': 'lot-item'},
                    {'tag': 'div', 'class': 'item'},
                    {'tag': 'div', 'class_contains': 'item'},  # class содержит "item"
                ]
                
                lot_elements = []
                for selector in selectors:
                    if 'class_contains' in selector:
                        lot_elements = soup.find_all(selector['tag'], 
                                                   class_=lambda x: x and selector['class_contains'] in x)
                    else:
                        lot_elements = soup.find_all(selector['tag'], class_=selector['class'])
                    
                    if lot_elements:
                        logger.info(f"Найдено {len(lot_elements)} лотов с селектором {selector}")
                        break
                
                if not lot_elements:
                    logger.warning(f"Не найдено лотов на странице: {url}")
                    # Пробуем найти любые элементы, которые могут быть лотами
                    lot_elements = soup.find_all(['div', 'a'], class_=True)
                    lot_elements = [el for el in lot_elements if any(word in str(el.get('class', [])).lower() 
                                                                    for word in ['item', 'lot', 'product', 'offer'])]
                
                for element in lot_elements[:30]:  # Ограничиваем для скорости
                    try:
                        # Извлечение данных
                        lot_data = extract_lot_data(element, url)
                        if not lot_data:
                            continue
                        
                        # Применение фильтров
                        if not apply_filters(lot_data, settings):
                            continue
                        
                        found_lots.append(lot_data)
                        
                    except Exception as e:
                        logger.debug(f"Ошибка обработки лота: {e}")
                        continue
                
    except asyncio.TimeoutError:
        logger.error(f"Таймаут при парсинге {url}")
    except Exception as e:
        logger.error(f"Ошибка парсинга {url}: {e}")
    
    return found_lots

def extract_lot_data(element, url: str) -> Optional[Dict[str, Any]]:
    """Извлечение данных из элемента лота"""
    try:
        # Название лота
        title = None
        title_selectors = [
            ('div.tc-desc-text', 'text'),
            ('div.item-title', 'text'),
            ('div.title', 'text'),
            ('h5', 'text'),
            ('h4', 'text'),
            ('h3', 'text'),
            ('a[href]', 'text'),
        ]
        
        for selector, attr in title_selectors:
            elem = element.select_one(selector)
            if elem:
                if attr == 'text':
                    title = elem.get_text(strip=True)
                else:
                    title = elem.get(attr, '')
                if title and len(title) > 3:
                    break
        
        if not title:
            # Пробуем извлечь из всего элемента
            title = element.get_text(' ', strip=True)[:200]
            if len(title) < 5:
                return None
        
        # Цена
        price_text = None
        price_selectors = [
            ('div.tc-price', 'text'),
            ('div.price', 'text'),
            ('span.price', 'text'),
            ('div.item-price', 'text'),
            ('b', 'text'),
            ('strong', 'text'),
            ('[class*="price"]', 'text'),
            ('[class*="cost"]', 'text'),
        ]
        
        for selector, attr in price_selectors:
            elem = element.select_one(selector)
            if elem:
                if attr == 'text':
                    price_text = elem.get_text(strip=True)
                else:
                    price_text = elem.get(attr, '')
                if price_text:
                    break
        
        # Ссылка
        link = None
        link_elem = element.find('a', href=True)
        if link_elem:
            link = link_elem['href']
        elif element.name == 'a' and element.get('href'):
            link = element['href']
        else:
            # Ищем любую ссылку внутри
            link_elem = element.select_one('a[href]')
            if link_elem:
                link = link_elem['href']
        
        if link and not link.startswith('http'):
            link = f"https://funpay.com{link}"
        
        # ID лота для отслеживания
        lot_id = f"{link}_{title[:50]}" if link else title[:100]
        
        return {
            'title': title[:150],
            'price_text': price_text or "Цена не указана",
            'price_value': extract_price(price_text) if price_text else None,
            'link': link or url,  # Если нет ссылки, используем URL категории
            'category_url': url,
            'lot_id': lot_id,
            'timestamp': datetime.now()
        }
        
    except Exception as e:
        logger.debug(f"Ошибка извлечения данных: {e}")
        return None

def apply_filters(lot_data: Dict[str, Any], settings: UserSettings) -> bool:
    """Применение фильтров к лоту"""
    # Фильтр по ключевым словам в названии
    title_lower = lot_data['title'].lower()
    keyword_match = any(keyword.lower() in title_lower for keyword in settings.keywords)
    
    if not keyword_match:
        return False
    
    # Фильтр по цене
    price = lot_data['price_value']
    if price is not None:
        if price < settings.min_price:
            return False
        if settings.max_price != float('inf') and price > settings.max_price:
            return False
    
    return True

async def find_lots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск лотов по сохраненным настройкам"""
    if not HAVE_ALL_DEPS:
        await send_error_message(update, "Библиотеки не установлены.")
        return
    
    user_id = update.effective_user.id
    
    if user_id not in user_settings:
        await update.message.reply_text(
            "❌ **Сначала настройте бота:**\n\n"
            "1. Отправьте ссылку на категорию FunPay\n"
            "2. `/keywords` - ключевые слова\n"
            "3. `/price` - диапазон цен\n"
            "4. `/find` - начать поиск"
        , parse_mode='Markdown')
        return
    
    settings = user_settings[user_id]
    
    if not settings.categories:
        await update.message.reply_text("❌ Нет добавленных категорий")
        return
    
    if not settings.keywords:
        await update.message.reply_text("❌ Не заданы ключевые слова. Используйте `/keywords`", parse_mode='Markdown')
        return
    
    # Показать параметры поиска
    max_price_display = f"{settings.max_price:.2f}" if settings.max_price != float('inf') else "∞"
    
    status_msg = await update.message.reply_text(
        f"🔍 **Начинаю поиск...**\n\n"
        f"📝 **Ключевые слова:** {', '.join(settings.keywords[:5])}{'...' if len(settings.keywords) > 5 else ''}\n"
        f"💰 **Цена:** {settings.min_price} - {max_price_display} ₽\n"
        f"📁 **Категорий:** {len(settings.categories)}\n\n"
        f"⏳ Это может занять несколько секунд..."
    , parse_mode='Markdown')
    
    all_found = []
    
    # Парсим каждую категорию
    for url in settings.categories:
        try:
            found = await parse_funpay_category(url, settings)
            all_found.extend(found)
            
            if found:
                logger.info(f"Найдено {len(found)} лотов в {url}")
                
        except Exception as e:
            logger.error(f"Ошибка при парсинге {url}: {e}")
            await update.message.reply_text(f"⚠️ Ошибка при обработке категории {url[:50]}...")
    
    # Сортируем по цене
    all_found.sort(key=lambda x: x['price_value'] or float('inf'))
    
    # Отправляем результаты
    if all_found:
        message = f"✅ **Найдено {len(all_found)} лотов:**\n\n"
        
        for i, lot in enumerate(all_found[:8], 1):  # Ограничиваем вывод
            price_display = f"{lot['price_value']:.2f} ₽" if lot['price_value'] else lot['price_text']
            
            message += f"**{i}. {price_display}**\n"
            message += f"📌 {lot['title']}\n"
            if lot['link'] and lot['link'] != lot['category_url']:
                message += f"🔗 [Открыть лот]({lot['link']})\n"
            message += f"📁 *Категория*\n"
            message += "―\n"
        
        if len(all_found) > 8:
            message += f"\n... и еще **{len(all_found) - 8}** лотов\n"
        
        message += f"\n💡 **Совет:** Для постоянного мониторинга используйте `/monitor start`"
        
        await status_msg.edit_text(message, parse_mode='Markdown', disable_web_page_preview=True)
    else:
        await status_msg.edit_text(
            "❌ **По вашим критериям ничего не найдено.**\n\n"
            "**Попробуйте:**\n"
            "• Расширить диапазон цен `/price`\n"
            "• Добавить больше ключевых слов `/keywords`\n"
            "• Проверить другие категории\n"
            "• Изменить ключевые слова (возможно, слишком строгие)"
        , parse_mode='Markdown')

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать текущие настройки"""
    user_id = update.effective_user.id
    
    if user_id not in user_settings:
        await update.message.reply_text("⚙️ **Настройки не заданы**\n\nИспользуйте `/help` для инструкций", parse_mode='Markdown')
        return
    
    settings = user_settings[user_id]
    
    message = "⚙️ **Ваши настройки:**\n\n"
    
    if settings.keywords:
        message += f"📝 **Ключевые слова ({len(settings.keywords)}):**\n"
        keywords_display = ', '.join([f'`{kw}`' for kw in settings.keywords[:7]])
        if len(settings.keywords) > 7:
            keywords_display += f' и еще {len(settings.keywords) - 7}'
        message += keywords_display + "\n\n"
    
    max_price_display = f"{settings.max_price:.2f}" if settings.max_price != float('inf') else '∞'
    message += f"💰 **Диапазон цен:** {settings.min_price} - {max_price_display} ₽\n\n"
    
    if settings.categories:
        message += f"📁 **Категории ({len(settings.categories)}):**\n"
        for i, url in enumerate(settings.categories[:3], 1):
            # Извлекаем ID категории из URL
            parts = url.split('/')
            cat_id = parts[-2] if len(parts) > 2 and parts[-2].isdigit() else parts[-1]
            message += f"{i}. Категория #{cat_id}\n"
        
        if len(settings.categories) > 3:
            message += f"... и еще {len(settings.categories) - 3}\n"
    
    message += "\n🛠 **Команды:**\n"
    message += "`/find` - начать поиск\n"
    message += "`/keywords` - изменить ключевые слова\n"
    message += "`/price` - изменить диапазон цен\n"
    message += "`/clear` - очистить все настройки\n"
    message += "`/help` - помощь"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def clear_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистить все настройки"""
    user_id = update.effective_user.id
    
    if user_id in user_settings:
        del user_settings[user_id]
    
    await update.message.reply_text("✅ **Все настройки очищены.**\n\nТеперь можно начать заново.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Справка по использованию"""
    help_text = """
🤖 **FunPay Парсер - Помощь**

📌 **Как начать:**
1. Отправьте боту ссылку на категорию FunPay
2. Задайте ключевые слова: `/keywords аккаунт, скин`
3. Установите диапазон цен: `/price 100 1000`
4. Найдите лоты: `/find`

🛠 **Основные команды:**
• `/keywords` - ключевые слова в названии лота
• `/price` - минимальная и максимальная цена
• `/find` - начать поиск по критериям
• `/settings` - текущие настройки
• `/clear` - очистить все настройки
• `/help` - эта справка

🔍 **Примеры категорий FunPay:**
• https://funpay.com/lots/123/ (замените 123 на ID категории)
• https://funpay.com/chips/456/ (игровая валюта)

💡 **Советы:**
• Используйте несколько ключевых слов через запятую
• Цены указывайте как "100 5000" (от 100 до 5000 ₽)
• Для поиска точных фраз используйте кавычки в ключевых словах
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def monitor_lots(context: ContextTypes.DEFAULT_TYPE):
    """Фоновая задача мониторинга новых лотов"""
    try:
        for user_id, settings in list(user_settings.items()):
            if not settings.categories or not settings.keywords:
                continue
            
            for url in settings.categories:
                try:
                    found = await parse_funpay_category(url, settings)
                    new_lots = []
                    
                    for lot in found:
                        lot_id = lot['lot_id']
                        if lot_id not in settings.monitored_lots:
                            new_lots.append(lot)
                            settings.monitored_lots[lot_id] = datetime.now()
                    
                    # Отправляем уведомления о новых лотах
                    for lot in new_lots[:3]:  # Не больше 3 за раз
                        price_display = f"{lot['price_value']:.2f} ₽" if lot['price_value'] else lot['price_text']
                        
                        message = f"🆕 **Новый лот!**\n\n"
                        message += f"💰 **{price_display}**\n"
                        message += f"📌 {lot['title']}\n"
                        if lot['link']:
                            message += f"🔗 [Открыть лот]({lot['link']})"
                        
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=message,
                            parse_mode='Markdown',
                            disable_web_page_preview=True
                        )
                        await asyncio.sleep(1)
                    
                    # Очищаем старые записи (старше 7 дней)
                    week_ago = datetime.now().timestamp() - 7 * 24 * 3600
                    old_lots = [lot_id for lot_id, ts in settings.monitored_lots.items() 
                              if ts.timestamp() < week_ago]
                    for lot_id in old_lots:
                        del settings.monitored_lots[lot_id]
                        
                except Exception as e:
                    logger.error(f"Ошибка мониторинга для user {user_id}: {e}")
    
    except Exception as e:
        logger.error(f"Ошибка в задаче мониторинга: {e}")

async def start_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск мониторинга"""
    user_id = update.effective_user.id
    
    if user_id not in user_settings:
        await update.message.reply_text("❌ Сначала настройте бота (категории и ключевые слова)")
        return
    
    # Удаляем старые задачи
    current_jobs = context.job_queue.get_jobs_by_name(f"monitor_{user_id}")
    for job in current_jobs:
        job.schedule_removal()
    
    # Добавляем новую задачу (проверка каждые 10 минут)
    context.job_queue.run_repeating(
        monitor_lots,
        interval=600,  # 10 минут
        first=5,
        chat_id=user_id,
        name=f"monitor_{user_id}",
        data={'user_id': user_id}
    )
    
    await update.message.reply_text(
        "✅ **Мониторинг запущен!**\n\n"
        "Бот будет проверять категории каждые 10 минут и присылать уведомления о новых лотах.\n\n"
        "🛑 Остановить: `/monitor stop`"
    , parse_mode='Markdown')

async def stop_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Остановка мониторинга"""
    user_id = update.effective_user.id
    job_name = f"monitor_{user_id}"
    
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    if current_jobs:
        for job in current_jobs:
            job.schedule_removal()
        await update.message.reply_text("⏹️ **Мониторинг остановлен**")
    else:
        await update.message.reply_text("ℹ️ Мониторинг не был запущен")

def main():
    """Запуск бота"""
    if not HAVE_ALL_DEPS:
        print("❌ Установите необходимые библиотеки:")
        print("pip install python-telegram-bot aiohttp beautifulsoup4")
        return
    
    try:
        application = Application.builder().token(TOKEN).build()
        
        # Регистрация обработчиков
        application.add_handler(CommandHandler("start", help_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("keywords", set_keywords))
        application.add_handler(CommandHandler("price", set_price_range))
        application.add_handler(CommandHandler("find", find_lots))
        application.add_handler(CommandHandler("settings", show_settings))
        application.add_handler(CommandHandler("clear", clear_settings))
        application.add_handler(CommandHandler("monitor", start_monitor))
        application.add_handler(CommandHandler("stop", stop_monitor))
        
        # Обработчик ссылок на категории
        application.add_handler(MessageHandler(
            filters.TEXT & filters.Regex(r'funpay\.com'),
            handle_category_link
        ))
        
        logger.info("Бот запущен...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")

if __name__ == '__main__':
    main()
