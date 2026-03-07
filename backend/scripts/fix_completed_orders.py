#!/usr/bin/env python3
"""
Скрипт: проставить collected_in_app=True для заказов, отмеченных «Собрано» в приложении.
Для заказов с completed_by_id (кто-то нажал «Собрано») — ставим collected_in_app=True.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.order import Order


def main():
    db = SessionLocal()
    try:
        to_fix = db.query(Order).filter(
            Order.completed_by_id.isnot(None),
            Order.collected_in_app.is_(False),
        ).all()
        if not to_fix:
            print("Нет заказов для исправления.")
            return
        for order in to_fix:
            order.collected_in_app = True
        db.commit()
        print(f"Проставлено collected_in_app=True для {len(to_fix)} заказов")
    finally:
        db.close()


if __name__ == "__main__":
    main()
