from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from datetime import datetime
from config import Config

# Инициализация базы данных
engine = create_engine(Config.DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    created_at = Column(DateTime, default=datetime.now)
    savings_goals = relationship("SavingsGoal", back_populates="user")
    budgets = relationship("Budget", back_populates="user")

class Category(Base):
    __tablename__ = 'categories'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'))
    user = relationship("User")

class Transaction(Base):
    __tablename__ = 'transactions'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    amount = Column(Float)
    category_id = Column(Integer, ForeignKey('categories.id'))
    is_income = Column(Boolean)
    created_at = Column(DateTime, default=datetime.now)
    category = relationship("Category")

class SavingsGoal(Base):
    __tablename__ = 'savings_goals'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    name = Column(String, nullable=False)
    target_amount = Column(Float, nullable=False)
    current_amount = Column(Float, default=0.0)
    target_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    user = relationship("User", back_populates="savings_goals")

class Budget(Base):
    __tablename__ = 'budgets'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    category_id = Column(Integer, ForeignKey('categories.id'))
    amount = Column(Float, nullable=False)
    period = Column(String, nullable=False)  # 'day', 'week', 'month', 'year'
    start_date = Column(DateTime, default=datetime.now)
    current_spent = Column(Float, default=0.0)
    user = relationship("User", back_populates="budgets")
    category = relationship("Category")

def init_db():
    """Создает все таблицы в базе данных"""
    Base.metadata.create_all(bind=engine)