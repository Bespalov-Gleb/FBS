"""
Сервис отметки заказа «Собрано».

WB: при включённом КИЗ сначала отправка КИЗ в Wildberries API (meta/sgtin), затем БД.
Ozon: только локально (как раньше).
"""
from sqlalchemy.orm import Session

from app.core.exceptions import MarketplaceAPIException
from app.core.security import decrypt_api_key
from app.models.marketplace import MarketplaceType
from app.models.order import Order
from app.models.scanned_kiz import ScannedKiz
from app.services.kiz_pool_service import assign_kiz_codes_fifo_for_order, mark_kiz_codes_used_for_order
from app.services.marketplace.wildberries import WildberriesClient
from app.utils.logger import logger

# Полный КИЗ (Честный ЗНАК / GS1) для API WB и хранения в БД; на этикетке текстом часто показывают 31 символ.
KIZ_STORAGE_MAX = 255


def _normalize_kiz(raw: str) -> str:
    """Нормализация скана КИЗ: убрать AIM-префиксы/мусор в начале, оставить полезные данные."""
    s = (raw or "").replace("\r", "").replace("\n", "").replace("\t", "").strip()
    # AIM-префиксы сканеров DataMatrix (не часть КИЗ)
    if s.startswith("]C1") or s.startswith("]c1") or s.startswith("]D2") or s.startswith("]d2") or s.startswith("]Q3") or s.startswith("]q3"):
        s = s[3:]
    # Служебные символы в начале (кроме GS=0x1D)
    while s and (ord(s[0]) < 32) and (s[0] != "\x1d"):
        s = s[1:]
    return s


def _kiz_31_for_wb(raw: str) -> str:
    """
    Укороченный КИЗ (31) для WB meta/sgtin:
    - GS (0x1D) или '>' считаем разделителем между базовой частью и хвостом 91/92
    - берём часть до разделителя, максимум 31 символ.
    """
    s = _normalize_kiz(raw).replace("\x1d", ">")
    if ">" in s:
        s = s.split(">", 1)[0]
    return s[:31].strip()


def _add_to_scanned_kiz(db: Session, user_id: int, kiz_code: str, order: Order) -> None:
    """Добавить КИЗ в таблицу отсканированных (для выгрузки в WB/Ozon)."""
    if not kiz_code or not kiz_code.strip():
        return
    sk = ScannedKiz(
        user_id=user_id,
        kiz_code=kiz_code[:KIZ_STORAGE_MAX],
        external_id=order.external_id,
        posting_number=order.posting_number,
        marketplace_id=order.marketplace_id,
    )
    db.add(sk)


class OrderCompleteService:
    """Отметка заказа как собранного; для WB с КИЗ — вызов API перед коммитом."""

    @staticmethod
    async def complete_order(
        order: Order,
        user_id: int,
        kiz_codes: list[str],
        db: Session,
    ) -> bool:
        """
        Отметить заказ «Собрано»: обновить в БД.

        Wildberries: если включён КИЗ и передан код — PUT .../orders/{id}/meta/sgtin;
        при ошибке API исключение, коммита нет.
        Ozon: только локально.
        """
        kiz_list = [_normalize_kiz(k)[:KIZ_STORAGE_MAX] for k in kiz_codes if k and _normalize_kiz(k)]
        if order.marketplace and order.marketplace.is_kiz_enabled and not kiz_list:
            # Автоматический подбор КИЗ из пула группы (FIFO) по настройкам администратора.
            kiz_list = assign_kiz_codes_fifo_for_order(
                db,
                order=order,
                required_count=order.quantity,
                completed_by_user_id=user_id,
            )
        if order.marketplace and order.marketplace.is_kiz_enabled and kiz_list:
            mark_kiz_codes_used_for_order(
                db,
                order=order,
                kiz_codes=kiz_list,
                completed_by_user_id=user_id,
            )
        first_kiz = kiz_list[0] if kiz_list else None

        mp = order.marketplace
        if not mp:
            for kiz in kiz_list:
                _add_to_scanned_kiz(db, user_id, kiz, order)
            order.complete(user_id=user_id, kiz_code=first_kiz)
            db.commit()
            return True

        if mp.type == MarketplaceType.OZON:
            for kiz in kiz_list:
                _add_to_scanned_kiz(db, user_id, kiz, order)
            order.complete(user_id=user_id, kiz_code=first_kiz)
            db.commit()
            return True

        if mp.type == MarketplaceType.WILDBERRIES:
            if mp.is_kiz_enabled and first_kiz:
                wb_kiz = _kiz_31_for_wb(first_kiz)
                if not wb_kiz:
                    raise MarketplaceAPIException(
                        message="WB: пустой КИЗ после нормализации",
                        marketplace="Wildberries",
                        detail="Не удалось выделить корректный КИЗ (31 символ) из скана.",
                        status_code=400,
                    )
                ed = order.extra_data or {}
                supplier = (ed.get("supplierStatus") or ed.get("supplier_status") or "").strip().lower()
                if supplier != "confirm":
                    raise MarketplaceAPIException(
                        message="WB: КИЗ можно передать только после добавления задания в поставку",
                        marketplace="Wildberries",
                        detail=(
                            f"По данным синхронизации статус задания: «{supplier or 'неизвестен'}», "
                            "нужен «confirm» (в поставке). Добавьте задание в поставку в кабинете WB и обновите заказы."
                        ),
                        status_code=400,
                    )
                api_key = decrypt_api_key(mp.api_key)
                async with WildberriesClient(api_key=api_key) as client:
                    # Перед отправкой КИЗ проверяем актуальный статус в WB (официальный endpoint /api/v3/orders/status).
                    try:
                        wb_order_id = int(str(order.external_id))
                    except (TypeError, ValueError):
                        wb_order_id = None
                    if wb_order_id is not None:
                        try:
                            statuses = await client.get_orders_statuses([wb_order_id])
                            wb_state = statuses.get(wb_order_id) or {}
                            wb_supplier = str(wb_state.get("supplier_status") or "").strip().lower()
                            wb_wb_status = str(wb_state.get("wb_status") or "").strip().lower()
                            logger.info(
                                "WB live status before KIZ submit",
                                extra={
                                    "order_id": order.id,
                                    "external_id": order.external_id,
                                    "wb_order_id": wb_order_id,
                                    "supplier_status_live": wb_supplier or None,
                                    "wb_status_live": wb_wb_status or None,
                                },
                            )
                            if wb_supplier and wb_supplier != "confirm":
                                raise MarketplaceAPIException(
                                    message="WB: задание не в статусе confirm (live check)",
                                    marketplace="Wildberries",
                                    detail=(
                                        f"WB live status: supplierStatus='{wb_supplier}', wbStatus='{wb_wb_status or '-'}'. "
                                        "Для передачи КИЗ нужен confirm (в сборке/в поставке)."
                                    ),
                                    status_code=409,
                                )
                        except MarketplaceAPIException:
                            raise
                        except Exception as e:
                            logger.warning(
                                "WB live status check failed before KIZ submit",
                                extra={
                                    "order_id": order.id,
                                    "external_id": order.external_id,
                                    "error": str(e),
                                },
                            )
                    try:
                        await client.add_kiz_code(str(order.external_id), wb_kiz)
                    except MarketplaceAPIException as e:
                        if e.status_code == 409:
                            ed = order.extra_data or {}
                            logger.error(
                                "WB KIZ 409 on complete: order status snapshot",
                                extra={
                                    "order_id": order.id,
                                    "external_id": order.external_id,
                                    "posting_number": order.posting_number,
                                    "marketplace_id": order.marketplace_id,
                                    "local_status": str(order.status.value) if order.status else None,
                                    "marketplace_status": order.marketplace_status,
                                    "supplier_status_from_sync": (ed.get("supplierStatus") or ed.get("supplier_status")),
                                    "collected_in_app": bool(order.collected_in_app),
                                    "kiz_len": len(wb_kiz),
                                    "wb_error_detail": e.detail,
                                },
                            )
                        raise
            for kiz in kiz_list:
                _add_to_scanned_kiz(db, user_id, kiz, order)
            order.complete(user_id=user_id, kiz_code=first_kiz)
            db.commit()
            return True

        return False
