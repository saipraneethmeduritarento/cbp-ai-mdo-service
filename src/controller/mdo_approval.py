"""
Controller for MDO approval workflows.
Orchestrates CRUD operations and external service calls.
"""
import uuid
from datetime import date
from typing import List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logger import logger
from ..crud.mdo_approval_request import crud_mdo_approval_request
from ..models.mdo_approval import ApprovalRequestRead
from ..services.igot_service import call_igot_create, call_igot_publish, extract_content_ids


class MDOApprovalController:
    """
    Business logic for MDO approval workflows.
    Coordinates between CRUD (database) and Service (external API) layers.
    """

    async def list_requests(
        self,
        db: AsyncSession,
        mdo_id: str,
        page: int = 1,
        page_size: int = 10,
        search: Optional[str] = None,
        status_filter: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Tuple[List[ApprovalRequestRead], int]:
        """List approval requests with pagination and filters."""
        normalized_status = status_filter.upper() if status_filter else None

        return await crud_mdo_approval_request.list_mdo_requests(
            db=db,
            mdo_id=mdo_id,
            page=page,
            page_size=page_size,
            search=search,
            status_filter=normalized_status,
            from_date=from_date,
            to_date=to_date,
        )

    async def get_request_detail(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        mdo_id: str,
    ) -> Optional[ApprovalRequestRead]:
        """Get a single approval request with items."""
        return await crud_mdo_approval_request.get_by_request_id_and_mdo(
            db=db, request_id=request_id, mdo_id=mdo_id
        )

    async def publish(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        mdo_id: str,
        plan_name: str,
        due_date: date,
        token: str,
    ) -> Tuple[Optional[ApprovalRequestRead], str]:
        """
        Approve and publish a pending approval request.

        Order of operations (fail-safe):
          1. Lock + validate the request is PENDING  (CRUD)
          2. Extract content IDs and designations     (Service)
          3. Call CBP create API                       (Service) ← fails fast, no DB writes yet
          4. Persist approval + audit trail            (CRUD)

        Returns:
            (updated request, igot_cbp_plan_id) or (None, "") if not found/not PENDING
        """
        # 1. Lock and fetch the request
        request = await crud_mdo_approval_request.get_pending_for_update(
            db=db, request_id=request_id, mdo_id=mdo_id
        )
        if not request:
            return None, ""

        # 2. Extract data for CBP API from items
        designations = [
            item.igot_designation_name or item.designation_name
            for item in request.items
        ]
        content_ids: List[str] = []
        for item in request.items:
            if item.cbp_plan_data:
                content_ids.extend(extract_content_ids(item.cbp_plan_data))

        if not content_ids:
            logger.warning(
                f"No content IDs found for request {request_id}. "
                "cbp_plan_data may be empty or missing selected_courses."
            )

        # 3. Call iGOT create + publish APIs BEFORE any DB writes; raises HTTPException(502) on failure
        igot_cbp_plan_id_str = await call_igot_create(
            token=token,
            org_id=request.state_center_id,
            plan_name=plan_name,
            due_date=due_date,
            designations=designations,
            content_ids=content_ids,
            is_apar=False,
        )

        await call_igot_publish(
            token=token,
            org_id=request.state_center_id,
            plan_id=igot_cbp_plan_id_str,
        )

        # 4. Persist all DB changes (approve request, create audit rows, approve items)
        updated = await crud_mdo_approval_request.persist_approval(
            db=db,
            request=request,
            request_id=request_id,
            mdo_id=mdo_id,
            plan_name=plan_name,
            due_date=due_date,
            igot_cbp_plan_id_str=igot_cbp_plan_id_str,
        )

        return updated, igot_cbp_plan_id_str

    async def reject_request(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        mdo_id: str,
        comments: str,
    ) -> Tuple[Optional[ApprovalRequestRead], int]:
        """
        Reject entire approval request (all items).

        Returns:
            (updated request, items_rejected_count) or (None, 0) if not found/not PENDING
        """
        return await crud_mdo_approval_request.reject_request(
            db=db,
            request_id=request_id,
            mdo_id=mdo_id,
            comments=comments,
        )

    async def reject_single_item(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        item_id: uuid.UUID,
        mdo_id: str,
        comments: str,
    ) -> Tuple[Optional[dict[str, str]], Optional[str]]:
        """
        Reject a specific item and recalculate parent request status.

        Returns:
            (result_dict, error_message)
        """
        return await crud_mdo_approval_request.reject_single_item(
            db=db,
            request_id=request_id,
            item_id=item_id,
            mdo_id=mdo_id,
            comments=comments,
        )


mdo_approval_controller = MDOApprovalController()
