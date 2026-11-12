from typing import override

from sqlalchemy import update
from sqlmodel import col, select

from a_domain.model.order.order import Order
from a_domain.model.order.recipient import Recipient
from a_domain.ports.order.order_repository import IOrderRepository
from a_domain.types.enums import OrderStatus
from a_domain.types.ids import OrderId, UserId
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.order_dto import OrderDTO


class OrderRepository(IOrderRepository):
    def __init__(self, db: DatabaseConnector) -> None:
        self._db = db

    @override
    async def get(self, order_id: OrderId) -> Order | None:
        async with self._db.session() as session:
            row = await session.get(OrderDTO, order_id)

        return row.to_domain() if row else None

    @override
    async def get_recipient(self, order_id: OrderId) -> Recipient | None:
        async with self._db.session() as session:
            row = await session.get(OrderDTO, order_id)

        return row.to_recipient() if row else None

    @override
    async def list_for_owner(self, owner_id: UserId, limit: int) -> list[Order]:
        statement = (
            select(OrderDTO)
            .where(col(OrderDTO.owner_id) == owner_id)
            .order_by(col(OrderDTO.created_at).desc(), col(OrderDTO.id).desc())
            .limit(limit)
        )

        async with self._db.session() as session:
            rows = (await session.execute(statement)).scalars().all()

        return [row.to_domain() for row in rows]

    @override
    async def add(self, order: Order, recipient: Recipient) -> None:
        async with self._db.session() as session:
            session.add(OrderDTO.from_domain(order, recipient))
            await session.commit()

    @override
    async def cancel(self, order: Order) -> bool:
        # One statement is the whole cancel. Its status condition is the guard: SQLite lets one writer in at a time, so
        # a second request's UPDATE runs after this one commits, finds the status already changed and matches no row.
        guarded_update = (
            update(OrderDTO)
            .where(col(OrderDTO.id) == order.id, col(OrderDTO.status).in_(OrderStatus.cancellable()))
            .values(
                status=order.status,
                cancelled_at=order.cancelled_at,
                cancelled_by_role=order.cancelled_by_role,
                cancel_reason=order.cancel_reason,
            )
            .returning(col(OrderDTO.id))
        )

        async with self._db.session() as session:
            stored = (await session.execute(guarded_update)).scalar_one_or_none() is not None
            await session.commit()

        return stored
