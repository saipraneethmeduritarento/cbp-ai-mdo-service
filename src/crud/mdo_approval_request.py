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
from ..core.logger import logger
from ..services.cbp_service import call_cbp_create, extract_content_ids


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

    async def approve_and_publish_request(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        mdo_id: str,
        plan_name: str,
        due_date: date,
        token: str,
        mdo_name: Optional[str] = None,
    ) -> tuple["ApprovalRequestRead", str]:
        """
        Approve and publish a pending approval request.

        Order of operations (fail-safe):
          1. Lock + validate the request is PENDING
          2. Call CBP create API to get publish_id  ← fails fast, no DB writes yet
          3. Update approval_requests status → APPROVED
          4. Create MdoApproval rows (with publish_id + isApar) for each item
          5. Update approval_request_items status → APPROVED
          6. Commit

        Returns:
            (updated ApprovalRequestRead, publish_id string)
            or (None, "") if not found / not PENDING
        """
        # 1. Lock the row to prevent concurrent modifications
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
        request = result.scalars().first()

        if not request or request.status != ApprovalStatus.PENDING:
            return None, ""

        # 2. Collect inputs for CBP API from each item
        designations = [
            item.igot_designation_name or item.designation_name
            for item in request.items
        ]
        content_ids: List[str] = []
        for item in request.items:
            if item.cbp_plan_data:
                content_ids.extend(extract_content_ids(item.cbp_plan_data))
        # Deduplicate while preserving order
        seen: set = set()
        content_ids = [c for c in content_ids if not (c in seen or seen.add(c))]

        if not content_ids:
            logger.warning(
                f"No content IDs found for request {request_id}. "
                "cbp_plan_data may be empty or missing selected_courses."
            )

        # Call CBP API BEFORE any DB writes; raises HTTPException(502) on failure
        publish_id_str = await call_cbp_create(
            token=token,
            org_id=request.state_center_id,
            plan_name=plan_name,
            due_date=due_date,
            designations=designations,
            content_ids=content_ids,
            is_apar=False,
        )
        publish_id = uuid.UUID(publish_id_str)

        # 3. Update the approval request status
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

        # 4 & 5. Create MdoApproval rows and update item statuses
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

        # 6. Single commit for all DB changes
        await db.commit()

        updated = await self.get_by_request_id_and_mdo(db, request_id, mdo_id)
        return updated, publish_id_str

    async def reject_request(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        mdo_id: str,
        comments: str,
        mdo_name: Optional[str] = None
    ) -> Optional[ApprovalRequestRead]:
        """
        Reject entire approval request (all designations).
        
        Args:
            db: Database session
            request_id: UUID of the approval request
            mdo_id: MDO identifier
            comments: Rejection reason/comments
            mdo_name: Optional MDO name for tracking
        """
        # Lock the row to prevent concurrent modifications
        stmt = (
            select(ApprovalRequestRead)
            .options(selectinload(ApprovalRequestRead.items))
            .where(
                and_(
                    ApprovalRequestRead.id == request_id,
                    ApprovalRequestRead.mdo_id == mdo_id
                )
            )
            .with_for_update()
        )
        result = await db.execute(stmt)
        request = result.scalars().first()
        
        if not request or request.status != ApprovalStatus.PENDING:
            return None
        
        stmt = (
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
                rejected_at=datetime.now(timezone.utc),
                reviewer_comments=comments
            )
        )
        await db.execute(stmt)

        # Update all items to rejected status
        items_update_stmt = (
            update(ApprovalRequestItemRead)
            .where(ApprovalRequestItemRead.approval_request_id == request_id)
            .values(
                status=ApprovalItemStatus.REJECTED,
                reviewer_comments=comments,
                rejected_at=datetime.now(timezone.utc)
            )
        )
        await db.execute(items_update_stmt)

        await db.commit()

        # Return the updated request
        return await self.get_by_request_id_and_mdo(db, request_id, mdo_id)

    async def reject_designations(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        mdo_id: str,
        designation_ids: List[uuid.UUID],
        comments: str
    ) -> Optional[ApprovalRequestRead]:
        """
        Reject specific designations within an approval request.
        
        Args:
            db: Database session
            request_id: UUID of the approval request
            mdo_id: MDO identifier
            designation_ids: List of designation item IDs to reject
            comments: Rejection reason/comments
        """
        # Lock the row to prevent concurrent modifications
        stmt = (
            select(ApprovalRequestRead)
            .options(selectinload(ApprovalRequestRead.items))
            .where(
                and_(
                    ApprovalRequestRead.id == request_id,
                    ApprovalRequestRead.mdo_id == mdo_id
                )
            )
            .with_for_update()
        )
        result = await db.execute(stmt)
        request = result.scalars().first()
        
        if not request or request.status != ApprovalStatus.PENDING:
            return None

        # Validate that all designation_ids belong to this request
        valid_item_ids = {item.id for item in request.items}
        invalid_ids = set(designation_ids) - valid_item_ids
        if invalid_ids:
            raise ValueError(f"Invalid designation IDs: {invalid_ids}")

        # Mark the specific items as rejected with new status
        stmt = (
            update(ApprovalRequestItemRead)
            .where(
                and_(
                    ApprovalRequestItemRead.id.in_(designation_ids),
                    ApprovalRequestItemRead.approval_request_id == request_id
                )
            )
            .values(
                status=ApprovalItemStatus.REJECTED,
                reviewer_comments=comments,
                rejected_at=datetime.now(timezone.utc)
            )
        )
        await db.execute(stmt)

        # Update the main request with reviewer info
        update_stmt = (
            update(ApprovalRequestRead)
            .where(ApprovalRequestRead.id == request_id)
            .values(
                reviewed_at=datetime.now(timezone.utc),
                reviewer_comments=comments
            )
        )
        await db.execute(update_stmt)

        await db.commit()

        # Return the updated request
        return await self.get_by_request_id_and_mdo(db, request_id, mdo_id)


crud_mdo_approval_request = CRUDMDOApprovalRequest()