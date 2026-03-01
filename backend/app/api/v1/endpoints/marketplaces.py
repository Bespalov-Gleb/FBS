"""
API endpoints для маркетплейсов
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decrypt_api_key, encrypt_api_key
from app.core.dependencies import CurrentUser
from app.models.marketplace import Marketplace, MarketplaceType
from app.models.user import User
from app.repositories.marketplace_repository import MarketplaceRepository
from app.schemas.marketplace import (
    MarketplaceCreate,
    MarketplaceResponse,
    MarketplaceUpdate,
)
from app.services.marketplace.ozon import OzonClient
from app.services.marketplace.wildberries import WildberriesClient

router = APIRouter(prefix="/marketplaces", tags=["Marketplaces"])


@router.get("", response_model=list[MarketplaceResponse])
def list_marketplaces(
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """Список подключённых маркетплейсов"""
    repo = MarketplaceRepository(db)
    items = repo.get_by_user(current_user.id)
    return [
        MarketplaceResponse(
            id=mp.id,
            type=mp.type.value,
            name=mp.name,
            is_kiz_enabled=mp.is_kiz_enabled,
            save_kiz_to_file=getattr(mp, "save_kiz_to_file", False),
            is_active=mp.is_active,
            last_sync_at=mp.last_sync_at,
        )
        for mp in items
    ]


@router.post("", response_model=MarketplaceResponse)
def create_marketplace(
    data: MarketplaceCreate,
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """Добавить подключение к маркетплейсу"""
    try:
        type_ = MarketplaceType(data.type)
    except ValueError:
        raise HTTPException(400, detail="type must be 'ozon' or 'wildberries'")
    if type_ == MarketplaceType.OZON and not data.client_id:
        raise HTTPException(400, detail="client_id required for Ozon")
    repo = MarketplaceRepository(db)
    mp = repo.create(
        user_id=current_user.id,
        type_=type_,
        name=data.name,
        api_key_encrypted=encrypt_api_key(data.api_key),
        client_id=data.client_id,
        is_kiz_enabled=data.is_kiz_enabled,
        save_kiz_to_file=data.save_kiz_to_file,
    )
    return MarketplaceResponse(
        id=mp.id,
        type=mp.type.value,
        name=mp.name,
        is_kiz_enabled=mp.is_kiz_enabled,
        save_kiz_to_file=getattr(mp, "save_kiz_to_file", False),
        is_active=mp.is_active,
        last_sync_at=mp.last_sync_at,
    )


@router.get("/{marketplace_id}", response_model=MarketplaceResponse)
def get_marketplace(
    marketplace_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """Получить маркетплейс"""
    repo = MarketplaceRepository(db)
    mp = repo.get(marketplace_id)
    if not mp or mp.user_id != current_user.id:
        raise HTTPException(404, detail="Marketplace not found")
    return MarketplaceResponse(
        id=mp.id,
        type=mp.type.value,
        name=mp.name,
        is_kiz_enabled=mp.is_kiz_enabled,
        save_kiz_to_file=getattr(mp, "save_kiz_to_file", False),
        is_active=mp.is_active,
        last_sync_at=mp.last_sync_at,
    )


@router.patch("/{marketplace_id}", response_model=MarketplaceResponse)
def update_marketplace(
    marketplace_id: int,
    data: MarketplaceUpdate,
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """Обновить маркетплейс"""
    repo = MarketplaceRepository(db)
    mp = repo.get(marketplace_id)
    if not mp or mp.user_id != current_user.id:
        raise HTTPException(404, detail="Marketplace not found")
    mp = repo.update(
        marketplace_id,
        name=data.name,
        is_kiz_enabled=data.is_kiz_enabled,
        save_kiz_to_file=data.save_kiz_to_file,
        is_active=data.is_active,
    )
    return MarketplaceResponse(
        id=mp.id,
        type=mp.type.value,
        name=mp.name,
        is_kiz_enabled=mp.is_kiz_enabled,
        save_kiz_to_file=getattr(mp, "save_kiz_to_file", False),
        is_active=mp.is_active,
        last_sync_at=mp.last_sync_at,
    )


@router.delete("/{marketplace_id}")
def delete_marketplace(
    marketplace_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """Удалить маркетплейс"""
    repo = MarketplaceRepository(db)
    mp = repo.get(marketplace_id)
    if not mp or mp.user_id != current_user.id:
        raise HTTPException(404, detail="Marketplace not found")
    repo.delete(marketplace_id)
    return {"ok": True}


@router.post("/{marketplace_id}/test")
async def test_marketplace(
    marketplace_id: int,
    db: Session = Depends(get_db),
    current_user: User = CurrentUser,
):
    """Тест подключения к API маркетплейса"""
    mp = db.query(Marketplace).filter(
        Marketplace.id == marketplace_id,
        Marketplace.user_id == current_user.id,
    ).first()
    if not mp:
        raise HTTPException(404, detail="Marketplace not found")
    api_key = decrypt_api_key(mp.api_key)
    if mp.type == MarketplaceType.OZON:
        if not mp.client_id:
            return {"success": False}
        async with OzonClient(api_key=api_key, client_id=mp.client_id) as client:
            ok = await client.test_connection()
    elif mp.type == MarketplaceType.WILDBERRIES:
        async with WildberriesClient(api_key=api_key) as client:
            ok = await client.test_connection()
    else:
        ok = False
    return {"success": ok}
