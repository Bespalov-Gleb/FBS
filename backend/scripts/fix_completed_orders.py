#!/usr/bin/env python3
"""
Скрипт: проставить completed_by_id для заказов со статусом COMPLETED, у которых он пустой.
Для заказов, которые были отмечены «Собрано» до добавления поля completed_by_id.
Использует assigned_to_id (кто работал с заказом) или первого админа.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole


def main():
    db = SessionLocal()
    try:
        fixed = db.query(Order).filter(
            Order.status == OrderStatus.COMPLETED,
            Order.completed_by_id.is_(None),
        ).all()
        if not fixed:
            print("Нет заказов для исправления.")
            return
        admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
        default_user_id = admin.id if admin else None
        updated = 0
        for order in fixed:
            order.completed_by_id = order.assigned_to_id or default_user_id
            if order.completed_by_id:
                updated += 1
        db.commit()
        print(f"Исправлено заказов: {updated} из {len(fixed)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
