"""
API v1 Router
"""
from fastapi import APIRouter

from app.api.v1.endpoints import auth, marketplaces, orders, print_settings, users, warehouses

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(marketplaces.router)
api_router.include_router(orders.router)
api_router.include_router(print_settings.router)
api_router.include_router(users.router)
api_router.include_router(warehouses.router)
