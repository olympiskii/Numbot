import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Токен бота
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        raise ValueError("Не указан BOT_TOKEN в .env файле")

    # Настройки базы данных
    DB_URL = "sqlite:///finance.db"  # Путь к SQLite базе данных
    
    # Другие настройки
    BUDGET_ALERT_PERCENT = 20  # Процент для уведомлений