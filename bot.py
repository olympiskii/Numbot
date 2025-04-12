import logging
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import Base, engine, SessionLocal, init_db, User, Category, Transaction, SavingsGoal, Budget
from config import Config

# Инициализация
init_db()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bot = Bot(token=Config.BOT_TOKEN)
dp = Dispatcher()

# Состояния FSM
class Form(StatesGroup):
    transaction_type = State()
    amount = State()
    category = State()
    new_category = State()
    savings_name = State()
    savings_target = State()
    savings_date = State()
    savings_deposit = State()
    budget_category = State()
    budget_amount = State()
    budget_period = State()
    report_period = State()

# =====================
# КЛАВИАТУРЫ
# =====================

def get_main_kb():
    kb = [
        [KeyboardButton(text="➕ Доход"), KeyboardButton(text="➖ Расход")],
        [KeyboardButton(text="📊 Отчет"), KeyboardButton(text="📝 Категории")],
        [KeyboardButton(text="💰 Бюджеты"), KeyboardButton(text="🎯 Накопления")],
        [KeyboardButton(text="ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)

async def get_categories_kb(user_id: int, action: str = "transaction"):
    with SessionLocal() as session:
        categories = session.query(Category).filter_by(user_id=user_id).all()
        builder = InlineKeyboardBuilder()
        for cat in categories:
            builder.button(text=cat.name, callback_data=f"{action}_cat_{cat.id}")
        
        if action in ["transaction", "budget"]:
            builder.button(text="➕ Создать категорию", callback_data=f"new_{action}_category")
        
        builder.adjust(1)
        return builder.as_markup()

# =====================
# ОСНОВНЫЕ КОМАНДЫ
# =====================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
        if not user:
            user = User(telegram_id=message.from_user.id)
            session.add(user)
            session.commit()
    
    await message.answer(
        "💰 <b>Финансовый помощник</b>\n\n"
        "Выберите действие:",
        reply_markup=get_main_kb(),
        parse_mode="HTML"
    )

@dp.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    help_text = (
        "📚 <b>Доступные команды:</b>\n\n"
        "➕ Доход - добавить доход\n"
        "➖ Расход - добавить расход\n"
        "📊 Отчет - просмотреть статистику\n"
        "📝 Категории - управление категориями\n"
        "💰 Бюджеты - установка лимитов\n"
        "🎯 Накопления - цели сбережений"
    )
    await message.answer(help_text, parse_mode="HTML")

# =====================
# ОБРАБОТКА ОТМЕНЫ И ВОЗВРАТА
# =====================

@dp.message(F.text == "❌ Отмена")
async def cancel_operation(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Операция отменена",
        reply_markup=get_main_kb()
    )

@dp.message(F.text == "🔙 На главную")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Главное меню:",
        reply_markup=get_main_kb()
    )

# =====================
# ТРАНЗАКЦИИ (ИСПРАВЛЕННЫЕ)
# =====================

@dp.message(F.text.in_(["➕ Доход", "➖ Расход"]))
async def start_transaction(message: Message, state: FSMContext):
    await state.update_data(transaction_type="income" if message.text == "➕ Доход" else "expense")
    await state.set_state(Form.amount)
    await message.answer("Введите сумму:", reply_markup=get_cancel_kb())

@dp.message(Form.amount)
async def process_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            raise ValueError
        await state.update_data(amount=amount)
        await state.set_state(Form.category)
        
        user_id = message.from_user.id
        await message.answer(
            "Выберите категорию:",
            reply_markup=await get_categories_kb(user_id, "transaction")
        )
    except ValueError:
        await message.answer("Введите корректную сумму (число больше 0):", reply_markup=get_cancel_kb())

@dp.callback_query(Form.category, F.data.startswith("transaction_cat_"))
async def select_category(callback: CallbackQuery, state: FSMContext):
    try:
        category_id = int(callback.data.split("_")[2])
        data = await state.get_data()
        
        with SessionLocal() as session:
            transaction = Transaction(
                user_id=callback.from_user.id,
                amount=data['amount'],
                category_id=category_id,
                is_income=data['transaction_type'] == 'income',
                created_at=datetime.now()
            )
            
            if not data['transaction_type'] == 'income':
                budgets = session.query(Budget).filter_by(category_id=category_id).all()
                for budget in budgets:
                    budget.current_spent += data['amount']
            
            session.add(transaction)
            session.commit()
        
        await callback.message.answer(
            f"✅ {'Доход' if data['transaction_type'] == 'income' else 'Расход'} {data['amount']} ₽ сохранен!",
            reply_markup=get_main_kb()
        )
    except Exception as e:
        logger.error(f"Ошибка сохранения транзакции: {e}")
        await callback.message.answer(
            "❌ Ошибка при сохранении транзакции",
            reply_markup=get_main_kb()
        )
    finally:
        await state.clear()

@dp.callback_query(Form.category, F.data == "new_transaction_category")
async def new_category(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название категории:", reply_markup=get_cancel_kb())
    await state.set_state(Form.new_category)

@dp.message(Form.new_category)
async def save_category(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Название не может быть пустым!", reply_markup=get_cancel_kb())
        return
    
    with SessionLocal() as session:
        exists = session.query(Category).filter_by(
            user_id=message.from_user.id,
            name=name
        ).first()
        if exists:
            await message.answer("Категория уже существует!", reply_markup=get_main_kb())
            await state.clear()
            return
        
        category = Category(
            name=name,
            user_id=message.from_user.id
        )
        session.add(category)
        session.commit()
        
        data = await state.get_data()
        if 'amount' in data:
            transaction = Transaction(
                user_id=message.from_user.id,
                amount=data['amount'],
                category_id=category.id,
                is_income=data['transaction_type'] == 'income',
                created_at=datetime.now()
            )
            session.add(transaction)
            session.commit()
            
            await message.answer(
                f"✅ Категория создана и транзакция сохранена!\n"
                f"Сумма: {data['amount']} ₽",
                reply_markup=get_main_kb()
            )
        else:
            await message.answer(
                f"✅ Категория «{name}» создана!",
                reply_markup=get_main_kb()
            )
        
        await state.clear()

# =====================
# КАТЕГОРИИ (ИСПРАВЛЕННЫЕ)
# =====================

@dp.message(F.text == "📝 Категории")
async def categories_menu(message: Message):
    with SessionLocal() as session:
        categories = session.query(Category).filter_by(user_id=message.from_user.id).all()
        
        if not categories:
            await message.answer("У вас пока нет категорий", reply_markup=get_main_kb())
            return
        
        text = "📝 Ваши категории:\n\n"
        for cat in categories:
            count = session.query(Transaction).filter_by(category_id=cat.id).count()
            total = session.query(func.sum(Transaction.amount)).filter_by(category_id=cat.id).scalar() or 0
            text += f"- {cat.name} ({count} транзакций, сумма: {total:.2f} ₽)\n"
        
        await message.answer(
            text,
            reply_markup=await get_categories_kb(message.from_user.id, "view")
        )

@dp.callback_query(F.data.startswith("view_cat_"))
async def view_category(callback: CallbackQuery):
    category_id = int(callback.data.split("_")[2])
    with SessionLocal() as session:
        category = session.get(Category, category_id)
        if not category:
            await callback.answer("Категория не найдена")
            return
        
        transactions = session.query(Transaction).filter_by(
            category_id=category_id
        ).order_by(Transaction.created_at.desc()).limit(10).all()
        
        response = [f"📊 <b>{category.name}</b>\n"]
        for t in transactions:
            response.append(
                f"{'➕' if t.is_income else '➖'} {t.amount} ₽ "
                f"({t.created_at.strftime('%d.%m.%Y')})"
            )
        
        if not transactions:
            response.append("\nВ этой категории пока нет транзакций")
        
        await callback.message.answer(
            "\n".join(response),
            parse_mode="HTML",
            reply_markup=get_main_kb()
        )
    await callback.answer()

# =====================
# ОТЧЕТЫ (ИСПРАВЛЕННЫЕ)
# =====================

@dp.message(F.text == "📊 Отчет")
async def report_menu(message: Message, state: FSMContext):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="За месяц")],
            [KeyboardButton(text="За год")],
            [KeyboardButton(text="За все время")],
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )
    await message.answer("Выберите период для отчета:", reply_markup=kb)
    await state.set_state(Form.report_period)

@dp.message(Form.report_period)
async def generate_report(message: Message, state: FSMContext):
    period = message.text
    with SessionLocal() as session:
        try:
            if period == "За месяц":
                date_from = datetime.now() - timedelta(days=30)
            elif period == "За год":
                date_from = datetime.now() - timedelta(days=365)
            else:
                date_from = datetime.min
            
            # Доходы и расходы
            income = session.query(func.sum(Transaction.amount)).filter(
                Transaction.user_id == message.from_user.id,
                Transaction.is_income == True,
                Transaction.created_at >= date_from
            ).scalar() or 0
            
            expense = session.query(func.sum(Transaction.amount)).filter(
                Transaction.user_id == message.from_user.id,
                Transaction.is_income == False,
                Transaction.created_at >= date_from
            ).scalar() or 0
            
            # Категории расходов
            expense_by_cat = session.query(
                Category.name,
                func.sum(Transaction.amount).label('total')
            ).join(Transaction).filter(
                Transaction.user_id == message.from_user.id,
                Transaction.is_income == False,
                Transaction.created_at >= date_from
            ).group_by(Category.name).order_by(func.sum(Transaction.amount).desc()).all()
            
            # Формируем отчет
            report = [
                f"📊 <b>Отчет {period.lower()}</b>",
                f"➖ Расходы: {expense:.2f} ₽",
                f"➕ Доходы: {income:.2f} ₽",
                f"🧮 Баланс: {income - expense:.2f} ₽",
                "",
                "<b>Расходы по категориям:</b>"
            ]
            
            for cat in expense_by_cat:
                report.append(f"- {cat.name}: {cat.total:.2f} ₽")
            
            if not expense_by_cat:
                report.append("\nНет данных о расходах")
            
            await message.answer(
                "\n".join(report),
                reply_markup=get_main_kb(),
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Ошибка генерации отчета: {e}")
            await message.answer(
                "Ошибка при генерации отчета",
                reply_markup=get_main_kb()
            )
        finally:
            await state.clear()

# =====================
# НАКОПЛЕНИЯ (ИСПРАВЛЕННЫЕ)
# =====================

@dp.message(F.text == "🎯 Накопления")
async def savings_menu(message: Message):
    with SessionLocal() as session:
        goals = session.query(SavingsGoal).filter_by(user_id=message.from_user.id).all()
        
        if not goals:
            kb = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="➕ Создать цель")],
                    [KeyboardButton(text="🔙 На главную")]
                ],
                resize_keyboard=True
            )
            await message.answer("У вас пока нет целей накопления.", reply_markup=kb)
            return
        
        text = "🎯 Ваши цели накопления:\n\n"
        for goal in goals:
            progress = (goal.current_amount / goal.target_amount) * 100
            remaining = goal.target_amount - goal.current_amount
            text += (
                f"📌 <b>{goal.name}</b>\n"
                f"Цель: {goal.target_amount:.2f} ₽\n"
                f"Накоплено: {goal.current_amount:.2f} ₽ ({progress:.1f}%)\n"
                f"Осталось: {remaining:.2f} ₽\n"
                f"{'Срок: ' + goal.target_date.strftime('%d.%m.%Y') if goal.target_date else ''}\n\n"
            )
        
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="➕ Создать цель"), KeyboardButton(text="💵 Пополнить")],
                [KeyboardButton(text="🔙 На главную")]
            ],
            resize_keyboard=True
        )
        
        await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.message(F.text == "➕ Создать цель")
async def start_create_goal(message: Message, state: FSMContext):
    await message.answer("Введите название цели:", reply_markup=get_cancel_kb())
    await state.set_state(Form.savings_name)

@dp.message(Form.savings_name)
async def process_goal_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите целевую сумму:", reply_markup=get_cancel_kb())
    await state.set_state(Form.savings_target)

@dp.message(Form.savings_target)
async def process_target_amount(message: Message, state: FSMContext):
    try: 
        amount = float(message.text)
        if amount <= 0:
            raise ValueError
        await state.update_data(target_amount=amount)
        
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Пропустить")],
                [KeyboardButton(text="❌ Отмена")]
            ],
            resize_keyboard=True
        )
        
        await message.answer(
            "Введите дату цели (ДД.ММ.ГГГГ) или нажмите 'Пропустить':",
            reply_markup=kb
        )
        await state.set_state(Form.savings_date)
    except ValueError:
        await message.answer("Пожалуйста, введите корректную сумму:", reply_markup=get_cancel_kb())

@dp.message(Form.savings_date)
async def process_target_date(message: Message, state: FSMContext):
    data = await state.get_data()
    target_date = None
    
    if message.text.lower() != "пропустить":
        try:
            target_date = datetime.strptime(message.text, "%d.%m.%Y").date()
            if target_date < datetime.now().date():
                await message.answer("Дата должна быть в будущем! Введите заново:", reply_markup=get_cancel_kb())
                return
        except ValueError:
            await message.answer("Неверный формат даты! Используйте ДД.ММ.ГГГГ", reply_markup=get_cancel_kb())
            return
    
    with SessionLocal() as session:
        goal = SavingsGoal(
            user_id=message.from_user.id,
            name=data['name'],
            target_amount=data['target_amount'],
            current_amount=0.0,
            target_date=target_date
        )
        session.add(goal)
        session.commit()
    
    await message.answer(
        f"✅ Цель «{data['name']}» создана!\n"
        f"Целевая сумма: {data['target_amount']} ₽\n"
        f"{'Срок: ' + target_date.strftime('%d.%m.%Y') if target_date else 'Без срока'}",
        reply_markup=get_main_kb()
    )
    await state.clear()

@dp.message(F.text == "💵 Пополнить")
async def start_deposit(message: Message, state: FSMContext):
    with SessionLocal() as session:
        goals = session.query(SavingsGoal).filter_by(user_id=message.from_user.id).all()
        
        if not goals:
            await message.answer("У вас пока нет целей для пополнения", reply_markup=get_main_kb())
            return
        
        builder = InlineKeyboardBuilder()
        for goal in goals:
            builder.button(
                text=f"{goal.name} ({goal.current_amount:.2f}₽/{goal.target_amount:.2f}₽)",
                callback_data=f"deposit_{goal.id}"
            )
        builder.adjust(1)
        
        await message.answer(
            "Выберите цель для пополнения:",
            reply_markup=builder.as_markup()
        )
        await state.set_state(Form.savings_deposit)

@dp.callback_query(Form.savings_deposit, F.data.startswith("deposit_"))
async def select_goal_for_deposit(callback: CallbackQuery, state: FSMContext):
    goal_id = int(callback.data.split("_")[1])
    await state.update_data(goal_id=goal_id)
    await callback.message.answer(
        "Введите сумму для пополнения:",
        reply_markup=get_cancel_kb()
    )
    await callback.answer()

@dp.message(Form.savings_deposit)
async def process_deposit_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            raise ValueError
        
        data = await state.get_data()
        
        with SessionLocal() as session:
            goal = session.get(SavingsGoal, data['goal_id'])
            if not goal:
                await message.answer("Цель не найдена")
                await state.clear()
                return
            
            goal.current_amount += amount
            session.commit()
            
            progress = (goal.current_amount / goal.target_amount) * 100
            remaining = goal.target_amount - goal.current_amount
            
            response = [
                f"✅ Вы пополнили цель <b>«{goal.name}»</b> на {amount:.2f} ₽",
                f"💰 Текущий баланс: {goal.current_amount:.2f} ₽ из {goal.target_amount:.2f} ₽",
                f"📊 Прогресс: {progress:.1f}%",
                f"📌 Осталось накопить: {remaining:.2f} ₽"
            ]
            
            if goal.target_amount <= goal.current_amount:
                response.append("\n🎉 Поздравляем! Цель достигнута!")
            
            await message.answer(
                "\n".join(response),
                reply_markup=get_main_kb(),
                parse_mode="HTML"
            )
        
        await state.clear()
    
    except ValueError:
        await message.answer("Пожалуйста, введите корректную сумму:", reply_markup=get_cancel_kb())

# =====================
# БЮДЖЕТЫ (НОВАЯ РЕАЛИЗАЦИЯ)
# =====================

@dp.message(F.text == "💰 Бюджеты")
async def budgets_menu(message: Message):
    with SessionLocal() as session:
        budgets = session.query(Budget).filter_by(user_id=message.from_user.id).all()
        
        if not budgets:
            kb = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="➕ Создать бюджет")],
                    [KeyboardButton(text="🔙 На главную")]
                ],
                resize_keyboard=True
            )
            await message.answer("У вас пока нет установленных бюджетов.", reply_markup=kb)
            return
        
        text = "💰 Ваши бюджеты:\n\n"
        for budget in budgets:
            remaining = budget.amount - budget.current_spent
            progress = (budget.current_spent / budget.amount) * 100 if budget.amount > 0 else 0
            
            status = "✅ В пределах" if remaining >= 0 else f"❌ Превышен на {abs(remaining):.2f} ₽"
            
            text += (
                f"📌 <b>{budget.category.name}</b>\n"
                f"Лимит: {budget.amount:.2f} ₽ ({budget.period})\n"
                f"Потрачено: {budget.current_spent:.2f} ₽ ({progress:.1f}%)\n"
                f"Остаток: {remaining:.2f} ₽\n"
                f"Статус: {status}\n\n"
            )
        
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="➕ Создать бюджет"), KeyboardButton(text="🔄 Сбросить")],
                [KeyboardButton(text="🔙 На главную")]
            ],
            resize_keyboard=True
        )
        
        await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.message(F.text == "➕ Создать бюджет")
async def start_create_budget(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await message.answer(
        "Выберите категорию для бюджета:",
        reply_markup=await get_categories_kb(user_id, "budget")
    )
    await state.set_state(Form.budget_category)

@dp.callback_query(Form.budget_category, F.data.startswith("budget_cat_"))
async def select_budget_category(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split("_")[2])
    await state.update_data(category_id=category_id)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="День"), KeyboardButton(text="Неделя")],
            [KeyboardButton(text="Месяц"), KeyboardButton(text="Год")],
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )
    
    await callback.message.answer(
        "Выберите период для бюджета:",
        reply_markup=kb
    )
    await state.set_state(Form.budget_period)
    await callback.answer()

@dp.message(Form.budget_period)
async def process_budget_period(message: Message, state: FSMContext):
    period = message.text.lower()
    if period not in ["день", "неделя", "месяц", "год"]:
        await message.answer("Пожалуйста, выберите период из предложенных вариантов")
        return
    
    await state.update_data(period=period)
    await message.answer("Введите сумму бюджета:", reply_markup=get_cancel_kb())
    await state.set_state(Form.budget_amount)

@dp.message(Form.budget_amount)
async def process_budget_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            raise ValueError
        
        data = await state.get_data()
        
        with SessionLocal() as session:
            # Проверяем, не существует ли уже бюджет для этой категории и периода
            existing = session.query(Budget).filter_by(
                user_id=message.from_user.id,
                category_id=data['category_id'],
                period=data['period']
            ).first()
            
            if existing:
                existing.amount = amount
                existing.current_spent = 0
                existing.start_date = datetime.now()
                session.commit()
                action = "обновлен"
            else:
                budget = Budget(
                    user_id=message.from_user.id,
                    category_id=data['category_id'],
                    amount=amount,
                    period=data['period'],
                    current_spent=0.0,
                    start_date=datetime.now()
                )
                session.add(budget)
                session.commit()
                action = "создан"
            
            category = session.get(Category, data['category_id'])
            
            await message.answer(
                f"✅ Бюджет для категории <b>«{category.name}»</b> {action}!\n"
                f"Лимит: {amount:.2f} ₽ ({data['period']})",
                reply_markup=get_main_kb(),
                parse_mode="HTML"
            )
        
        await state.clear()
    
    except ValueError:
        await message.answer("Пожалуйста, введите корректную сумму (число больше 0):", reply_markup=get_cancel_kb())

@dp.message(F.text == "🔄 Сбросить")
async def reset_budgets(message: Message):
    with SessionLocal() as session:
        budgets = session.query(Budget).filter_by(user_id=message.from_user.id).all()
        
        if not budgets:
            await message.answer("У вас нет бюджетов для сброса", reply_markup=get_main_kb())
            return
        
        for budget in budgets:
            budget.current_spent = 0
            budget.start_date = datetime.now()
        
        session.commit()
    
    await message.answer(
        "✅ Все бюджеты сброшены (текущие траты обнулены, период начат заново)",
        reply_markup=get_main_kb()
    )

# Обновим обработчик транзакций для проверки бюджета
@dp.callback_query(Form.category, F.data.startswith("transaction_cat_"))
async def select_category(callback: CallbackQuery, state: FSMContext):
    try:
        category_id = int(callback.data.split("_")[2])
        data = await state.get_data()
        
        with SessionLocal() as session:
            transaction = Transaction(
                user_id=callback.from_user.id,
                amount=data['amount'],
                category_id=category_id,
                is_income=data['transaction_type'] == 'income',
                created_at=datetime.now()
            )
            
            if not data['transaction_type'] == 'income':
                budgets = session.query(Budget).filter_by(category_id=category_id).all()
                budget_warnings = []
                
                for budget in budgets:
                    budget.current_spent += data['amount']
                    remaining = budget.amount - budget.current_spent
                    
                    if remaining < 0:
                        budget_warnings.append(
                            f"⚠️ Превышен бюджет для категории {budget.category.name}!\n"
                            f"Лимит: {budget.amount:.2f} ₽ ({budget.period})\n"
                            f"Потрачено: {budget.current_spent:.2f} ₽\n"
                            f"Превышение: {abs(remaining):.2f} ₽"
                        )
                
                session.add(transaction)
                session.commit()
                
                response = [
                    f"✅ {'Доход' if data['transaction_type'] == 'income' else 'Расход'} {data['amount']} ₽ сохранен!"
                ]
                
                if budget_warnings:
                    response.append("\n".join(budget_warnings))
                
                await callback.message.answer(
                    "\n".join(response),
                    reply_markup=get_main_kb()
                )
            else:
                session.add(transaction)
                session.commit()
                await callback.message.answer(
                    f"✅ {'Доход' if data['transaction_type'] == 'income' else 'Расход'} {data['amount']} ₽ сохранен!",
                    reply_markup=get_main_kb()
                )
                
    except Exception as e:
        logger.error(f"Ошибка сохранения транзакции: {e}")
        await callback.message.answer(
            "❌ Ошибка при сохранении транзакции",
            reply_markup=get_main_kb()
        )
    finally:
        await state.clear()

# =====================
# ЗАПУСК БОТА
# =====================

async def main():
    logger.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        logger.info("Бот остановлен")

if __name__ == "__main__":
    asyncio.run(main())