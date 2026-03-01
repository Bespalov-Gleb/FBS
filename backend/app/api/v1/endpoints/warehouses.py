"""
API endpoints для складов маркетплейсов
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentAdminUser, CurrentUser
from app.models.user import User
from app.models.marketplace import Marketplace
from app.repositories.warehouse_repository import WarehouseRepository
from app.services.warehouse_service import WarehouseService

router = APIRouter(prefix="/warehouses", tags=["Warehouses"])


class WarehouseResponse(BaseModel):
    """Ответ со списком складов"""
    id: int
    external_warehouse_id: str
    name: str
    color: str | None


class WarehouseColorUpdate(BaseModel):
    """Обновление цвета склада"""
    color: str


@router.get("", response_model=list[WarehouseResponse])
def list_all_warehouses(
    marketplace_type: Optional[str] = Query(None, description="ozon | wildberries"),
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """Список всех складов пользователя (для фильтра «Все» / «Ozon все» / «WB все»)"""
    warehouses = WarehouseRepository.get_all_for_user(
        db, current_user.id, marketplace_type=marketplace_type
    )
    return [
        WarehouseResponse(
            id=w.id,
            external_warehouse_id=w.external_warehouse_id,
            name=w.name,
            color=w.color,
        )
        for w in warehouses
    ]


@router.get(
    "/marketplace/{marketplace_id}",
    response_model=list[WarehouseResponse],
)
def list_warehouses(
    marketplace_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """Список складов маркетплейса (для настройки цветов)"""
    marketplace = db.query(Marketplace).filter(
        Marketplace.id == marketplace_id,
        Marketplace.user_id == current_user.id,
    ).first()
    if not marketplace:
        raise HTTPException(404, detail="Marketplace not found")
    warehouses = WarehouseService.get_warehouses_for_marketplace(marketplace_id, db)
    return [
        WarehouseResponse(
            id=w.id,
            external_warehouse_id=w.external_warehouse_id,
            name=w.name,
            color=w.color,
        )
        for w in warehouses
    ]


@router.post(
    "/marketplace/{marketplace_id}/sync",
)
async def sync_warehouses(
    marketplace_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """Синхронизация складов из API маркетплейса."""
    marketplace = db.query(Marketplace).filter(
        Marketplace.id == marketplace_id,
        Marketplace.user_id == current_user.id,
    ).first()
    if not marketplace:
        raise HTTPException(status_code=404, detail="Marketplace not found")
    
    count = await WarehouseService.sync_warehouses(marketplace, db)
    return {"synced": count, "marketplace_id": marketplace_id}


@router.patch(
    "/{warehouse_id}/color",
    response_model=WarehouseResponse,
)
def update_warehouse_color(
    warehouse_id: int,
    data: WarehouseColorUpdate,
    db: Session = Depends(get_db),
    current_user: User = CurrentAdminUser,
):
    """Обновить цвет склада (HEX, например #FF5733)"""
    from app.models.warehouse import Warehouse

    wh = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not wh:
        raise HTTPException(404, detail="Warehouse not found")
    mp = db.query(Marketplace).filter(
        Marketplace.id == wh.marketplace_id,
        Marketplace.user_id == current_user.id,
    ).first()
    if not mp:
        raise HTTPException(404, detail="Warehouse not found")
    result = WarehouseService.update_warehouse_color(
        warehouse_id=warehouse_id,
        color=data.color,
        db=db,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return WarehouseResponse(**result)
