"""
CRUD operations for MDO Portal approval request management
"""
import uuid
from datetime import datetime, date, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, desc, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload, noload

from ..models.mdo_approval import ApprovalRequestRead, ApprovalRequestItemRead, MdoApproval
from ..schemas.comman import ApprovalStatus, ApprovalItemStatus


class CRUDMDOApprovalRequest:
    """
    CRUD methods for MDO Portal to manage approval requests
    """

    async def list_mdo_requests(
        self,
        db: AsyncSession,
        mdo_id: str,
        page: int = 1,
        page_size: int = 10,
        search: Optional[str] = None,
        status_filter: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None
    ) -> Tuple[List[ApprovalRequestRead], int]:
        """
        List approval requests assigned to a specific MDO with pagination and filters.
        Returns (items, total_count).
        """
        conditions = [ApprovalRequestRead.mdo_id == mdo_id]

        # Search: partial match on request_name
        if search:
            search_term = search.strip()
            conditions.append(
                ApprovalRequestRead.request_name.ilike(f"%{search_term}%")
            )

        # Status filter
        if status_filter:
            conditions.append(ApprovalRequestRead.status == status_filter)

        # Date range filter on created_at
        if from_date:
            conditions.append(ApprovalRequestRead.created_at >= from_date)
        if to_date:
            conditions.append(ApprovalRequestRead.created_at <= to_date)

        where_clause = and_(*conditions)

        # Count total
        count_stmt = select(func.count()).select_from(
            ApprovalRequestRead).where(where_clause)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar_one()

        # Fetch page - Don't load relationships to avoid field mismatch issues
        offset = (page - 1) * page_size
        stmt = (
            select(ApprovalRequestRead)
            .options(noload(ApprovalRequestRead.items))  # Don't load the items relationship
            .where(where_clause)
            .order_by(desc(ApprovalRequestRead.created_at))
            .offset(offset)
            .limit(page_size)
        )
        result = await db.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def get_by_request_id_and_mdo(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        mdo_id: str
    ) -> Optional[ApprovalRequestRead]:
        """
        Get an approval request by its UUID and MDO ID.
        Ensures the request is assigned to the specified MDO.
        """
        stmt = (
            select(ApprovalRequestRead)
            .options(selectinload(ApprovalRequestRead.items))
            .where(
                and_(
                    ApprovalRequestRead.id == request_id,
                    ApprovalRequestRead.mdo_id == mdo_id
                )
            )
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def _get_for_update(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        mdo_id: str,
    ) -> Optional[ApprovalRequestRead]:
        """
        Lock and fetch an approval request with items for update.
        Returns None if not found. Does NOT check status.
        """
        stmt = (
            select(ApprovalRequestRead)
            .options(selectinload(ApprovalRequestRead.items))
            .where(
                and_(
                    ApprovalRequestRead.id == request_id,
                    ApprovalRequestRead.mdo_id == mdo_id,
                )
            )
            .with_for_update()
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_pending_for_update(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        mdo_id: str,
    ) -> Optional[ApprovalRequestRead]:
        """
        Lock and fetch a PENDING approval request for update.
        Returns None if not found or not PENDING.
        """
        request = await self._get_for_update(db, request_id, mdo_id)
        if not request or request.status != ApprovalStatus.PENDING:
            return None
        return request

    async def persist_approval(
        self,
        db: AsyncSession,
        request: ApprovalRequestRead,
        request_id: uuid.UUID,
        mdo_id: str,
        plan_name: str,
        due_date: date,
        publish_id_str: str,
    ) -> Optional[ApprovalRequestRead]:
        """
        Persist approval: update request status, create MdoApproval audit rows,
        update item statuses. Caller must have already locked the row and
        obtained publish_id from the external API.

        Returns the updated request.
        """
        publish_id = uuid.UUID(publish_id_str)

        # Update the approval request status
        await db.execute(
            update(ApprovalRequestRead)
            .where(
                and_(
                    ApprovalRequestRead.id == request_id,
                    ApprovalRequestRead.mdo_id == mdo_id,
                    ApprovalRequestRead.status == ApprovalStatus.PENDING,
                )
            )
            .values(
                status=ApprovalStatus.APPROVED,
                updated_at=datetime.now(timezone.utc),
            )
        )

        # Create MdoApproval rows and update item statuses
        due_dt = datetime.combine(due_date, datetime.min.time()).replace(tzinfo=timezone.utc)

        for item in request.items:
            db.add(
                MdoApproval(
                    approval_request_id=request_id,
                    approval_request_item_id=item.id,
                    mdo_id=mdo_id,
                    designation_name=item.designation_name,
                    plan_name=plan_name,
                    due_date=due_dt,
                    user_id=request.user_id,
                    publish_id=publish_id,
                )
            )
            await db.execute(
                update(ApprovalRequestItemRead)
                .where(ApprovalRequestItemRead.id == item.id)
                .values(status=ApprovalItemStatus.APPROVED)
            )

        await db.commit()

        return await self.get_by_request_id_and_mdo(db, request_id, mdo_id)

    async def reject_request(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        mdo_id: str,
        comments: str,
    ) -> Tuple[Optional[ApprovalRequestRead], int]:
        """
        Reject entire approval request (all designations).

        Returns:
            (updated request, items_rejected_count)
            or (None, 0) if not found / not PENDING
        """
        request = await self.get_pending_for_update(db, request_id, mdo_id)

        if not request:
            return None, 0

        items_count = len(request.items)

        # Update request status
        now = datetime.now(timezone.utc)
        await db.execute(
            update(ApprovalRequestRead)
            .where(
                and_(
                    ApprovalRequestRead.id == request_id,
                    ApprovalRequestRead.mdo_id == mdo_id,
                    ApprovalRequestRead.status == ApprovalStatus.PENDING
                )
            )
            .values(
                status=ApprovalStatus.REJECTED,
                rejected_at=now,
                reviewer_comments=comments,
                updated_at=now,
            )
        )

        # Update all items to rejected status
        await db.execute(
            update(ApprovalRequestItemRead)
            .where(ApprovalRequestItemRead.approval_request_id == request_id)
            .values(
                status=ApprovalItemStatus.REJECTED,
                reviewer_comments=comments,
                rejected_at=now,
            )
        )

        await db.commit()

        updated = await self.get_by_request_id_and_mdo(db, request_id, mdo_id)
        return updated, items_count

    async def reject_single_item(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        item_id: uuid.UUID,
        mdo_id: str,
        comments: str,
    ) -> Tuple[Optional[dict[str, str]], Optional[str]]:
        """
        Reject a specific item within an approval request and recalculate parent status.

        Returns:
            (result_dict, error_message)
            result_dict contains: designation_name, request_status
            error_message is set if validation fails, result_dict is None
        """
        # Need separate not_found vs invalid_status errors, so can't use get_pending_for_update
        request = await self._get_for_update(db, request_id, mdo_id)

        if not request:
            return None, "not_found"

        if request.status != ApprovalStatus.PENDING:
            return None, f"invalid_status:{request.status}"

        # Find the target item
        target_item = None
        for item in request.items:
            if item.id == item_id:
                target_item = item
                break

        if not target_item:
            return None, "item_not_found"

        if target_item.status == ApprovalItemStatus.REJECTED:
            return None, "already_rejected"

        # Reject the item
        now = datetime.now(timezone.utc)
        await db.execute(
            update(ApprovalRequestItemRead)
            .where(ApprovalRequestItemRead.id == item_id)
            .values(
                status=ApprovalItemStatus.REJECTED,
                reviewer_comments=comments,
                rejected_at=now,
            )
        )

        # Recalculate parent request status based on all item statuses
        # (use in-memory items, accounting for the one we just rejected)
        pending_count = 0
        approved_count = 0
        rejected_count = 0
        for item in request.items:
            item_status = ApprovalItemStatus.REJECTED if item.id == item_id else item.status
            if item_status == ApprovalItemStatus.PENDING:
                pending_count += 1
            elif item_status == ApprovalItemStatus.APPROVED:
                approved_count += 1
            elif item_status == ApprovalItemStatus.REJECTED:
                rejected_count += 1

        new_status = ApprovalStatus.PENDING
        if pending_count == 0:
            if rejected_count > 0 and approved_count == 0:
                new_status = ApprovalStatus.REJECTED
                await db.execute(
                    update(ApprovalRequestRead)
                    .where(ApprovalRequestRead.id == request_id)
                    .values(
                        status=ApprovalStatus.REJECTED,
                        rejected_at=now,
                        updated_at=now,
                    )
                )
            elif approved_count > 0:
                new_status = ApprovalStatus.APPROVED
                await db.execute(
                    update(ApprovalRequestRead)
                    .where(ApprovalRequestRead.id == request_id)
                    .values(
                        status=ApprovalStatus.APPROVED,
                        updated_at=now,
                    )
                )

        await db.commit()

        return {
            "designation_name": target_item.designation_name,
            "request_status": new_status,
        }, None


crud_mdo_approval_request = CRUDMDOApprovalRequest()