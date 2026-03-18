"""
MDO Approval API endpoints.
Allows MDO admins to view, approve, and reject approval requests.
"""
import asyncio
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db_session
from ...core.logger import logger
from ...crud.mdo_approval_request import crud_mdo_approval_request
from ...models.mdo_approval import ApprovalRequestRead, ApprovalRequestItemRead, MdoApproval
from ...schemas.comman import ApprovalStatus
from ...schemas.mdo_approval import (
    ApprovalRequestListItem,
    ApprovalRequestDetail,
    ApproveRequestBody,
    RejectRequestBody,
    RejectItemBody,
    ApprovalActionResponse,
    PaginatedApprovalRequestsResponse,
    PaginationMetadata,
    ApprovalRequestFilters
)

router = APIRouter(prefix="/mdo", tags=["MDO Approval"])


@router.get("/approval-requests/list", response_model=PaginatedApprovalRequestsResponse)
async def get_approval_requests(
    mdo_id: str = Query(..., description="MDO ID of the logged-in MDO admin"),
    page: int = Query(1, ge=1, description="Page number (starts from 1)"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    search: Optional[str] = Query(None, description="Search by request name or state/center name"),
    status_filter: Optional[str] = Query(None, description="Filter by status (pending, IN_REVIEW, approved, rejected)"),
    from_date: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Get paginated list of approval requests for the MDO.
    Supports search and filtering by status and date range.
    """
    try:
        items, total_count = await crud_mdo_approval_request.list_mdo_requests(
            db=db,
            mdo_id=mdo_id,
            page=page,
            page_size=page_size,
            search=search,
            status_filter=status_filter,
            from_date=from_date,
            to_date=to_date
        )
        
        # Calculate pagination metadata
        total_pages = (total_count + page_size - 1) // page_size
        has_next = page < total_pages
        has_prev = page > 1
        
        return PaginatedApprovalRequestsResponse(
            items=[ApprovalRequestListItem.model_validate(item) for item in items],
            pagination=PaginationMetadata(
                current_page=page,
                page_size=page_size,
                total_items=total_count,
                total_pages=total_pages,
                has_next=has_next,
                has_prev=has_prev
            ),
            filters=ApprovalRequestFilters(
                search=search,
                status_filter=status_filter,
                from_date=from_date,
                to_date=to_date
            )
        )
    except Exception as e:
        logger.exception(f"Error fetching approval requests for MDO {mdo_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch approval requests"
        )



@router.get("/approval-requests/{request_id}", response_model=ApprovalRequestDetail)
async def get_approval_request_detail(
    request_id: UUID,
    mdo_id: str = Query(..., description="MDO ID of the logged-in MDO admin"),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Get detailed view of a specific approval request with all items.
    Automatically updates status to 'IN_REVIEW' if currently 'pending'.
    """
    try:
        stmt = select(ApprovalRequestRead).where(
            ApprovalRequestRead.id == request_id,
            ApprovalRequestRead.mdo_id == mdo_id
        )
        result = await db.execute(stmt)
        request = result.scalar_one_or_none()

        if not request:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval request not found or access denied"
            )

        logger.info(f"Current request status: '{request.status}' for request {request_id}")

        # Check if status needs to be updated (case-insensitive comparison)
        if request.status.upper() == "PENDING":
            logger.info(f"Updating request {request_id} status from '{request.status}' to 'IN_REVIEW'")
            
            # Use text() to cast the enum value properly for PostgreSQL
            update_stmt = (
                update(ApprovalRequestRead)
                .where(ApprovalRequestRead.id == request_id)
                .values(
                    status=text("'IN_REVIEW'::approval_status_enum"),
                    reviewed_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
            )
            await db.execute(update_stmt)
            await db.commit()
            
            # Fetch the updated request to ensure we have the latest status
            stmt = select(ApprovalRequestRead).where(
                ApprovalRequestRead.id == request_id,
                ApprovalRequestRead.mdo_id == mdo_id
            )
            result = await db.execute(stmt)
            request = result.scalar_one()
            logger.info(f"Successfully updated request {request_id} status to '{request.status}'")

        return ApprovalRequestDetail.model_validate(request)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching approval request detail")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch approval request details"
        )


@router.post("/approval-requests/approve", response_model=ApprovalActionResponse)
async def approve_request(
    body: ApproveRequestBody,
    mdo_id: str = Query(..., description="MDO ID of the logged-in MDO admin"),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Approve all or specific items in an approval request.
    Creates mdo_approval records and updates item statuses.
    """
    try:
        request_stmt = select(ApprovalRequestRead).where(
            ApprovalRequestRead.id == body.request_id,
            ApprovalRequestRead.mdo_id == mdo_id
        )
        request_result = await db.execute(request_stmt)
        request = request_result.scalar_one_or_none()

        if not request:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval request not found or access denied"
            )

        if request.status != "IN_REVIEW":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve request with status '{request.status}'. Must be 'IN_REVIEW'. Please view the request details first to update status."
            )

        # Get all items in the request for approval
        items_stmt = select(ApprovalRequestItemRead).where(
            ApprovalRequestItemRead.approval_request_id == body.request_id
        )

        items_result = await db.execute(items_stmt)
        items_to_approve = items_result.scalars().all()

        if not items_to_approve:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No items found to approve"
            )

        async def approve_item(item: ApprovalRequestItemRead):
            await db.execute(
                update(ApprovalRequestItemRead)
                .where(ApprovalRequestItemRead.id == item.id)
                .values(
                    status=text("'APPROVED'::approval_status_enum")
                )
            )
            db.add(MdoApproval(
                approval_request_id=body.request_id,
                approval_request_item_id=item.id,
                mdo_id=mdo_id,
                designation_name=item.designation_name,
                plan_name=body.plan_name,
                due_date=body.due_date,
                user_id=request.user_id
            ))

        await asyncio.gather(*[approve_item(item) for item in items_to_approve])

        # Since we're approving all items in the request, set status to approved
        await db.execute(
            update(ApprovalRequestRead)
            .where(ApprovalRequestRead.id == body.request_id)
            .values(status=text("'APPROVED'::approval_status_enum"), updated_at=datetime.now(timezone.utc))
        )
        await db.commit()

        logger.info(f"Approved {len(items_to_approve)} items for request {body.request_id}")

        return ApprovalActionResponse(
            message=f"Successfully approved {len(items_to_approve)} designation(s)",
            request_status="approved",
            items_processed=len(items_to_approve),
            item_ids=[item.id for item in items_to_approve]
        )

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"Error approving request")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to approve request"
        )


@router.post("/approval-requests/reject", response_model=ApprovalActionResponse)
async def reject_request(
    body: RejectRequestBody,
    mdo_id: str = Query(..., description="MDO ID of the logged-in MDO admin"),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Reject all or specific items in an approval request.
    Creates mdo_approval records with rejection comments and updates item statuses.
    """
    try:
        request_stmt = select(ApprovalRequestRead).where(
            ApprovalRequestRead.id == body.request_id,
            ApprovalRequestRead.mdo_id == mdo_id
        )
        request_result = await db.execute(request_stmt)
        request = request_result.scalar_one_or_none()

        if not request:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval request not found or access denied"
            )

        if request.status != "IN_REVIEW":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot reject request with status '{request.status}'. Must be 'IN_REVIEW'. Please view the request details first to update status."
            )

        # Get all items in the request for rejection
        items_stmt = select(ApprovalRequestItemRead).where(
            ApprovalRequestItemRead.approval_request_id == body.request_id
        )

        items_result = await db.execute(items_stmt)
        items_to_reject = items_result.scalars().all()

        if not items_to_reject:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No items found to reject"
            )

        async def reject_item(item: ApprovalRequestItemRead):
            await db.execute(
                update(ApprovalRequestItemRead)
                .where(ApprovalRequestItemRead.id == item.id)
                .values(
                    status=text("'REJECTED'::approval_status_enum"),
                    reviewer_comments=body.rejection_comment,
                    rejected_at=datetime.now(timezone.utc)
                )
            )

        await asyncio.gather(*[reject_item(item) for item in items_to_reject])

        # Since we're rejecting all items in the request, set status to rejected
        await db.execute(
            update(ApprovalRequestRead)
            .where(ApprovalRequestRead.id == body.request_id)
            .values(
                status=text("'REJECTED'::approval_status_enum"),
                reviewer_comments=body.rejection_comment,
                rejected_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
        )

        await db.commit()

        logger.info(f"Rejected {len(items_to_reject)} items for request {body.request_id}")

        return ApprovalActionResponse(
            message=f"Successfully rejected {len(items_to_reject)} designation(s)",
            request_status="rejected",
            items_processed=len(items_to_reject),
            item_ids=[item.id for item in items_to_reject]
        )

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"Error rejecting request")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reject request"
        )


@router.post("/approval-requests/items/reject")
async def reject_approval_request_item(
    body: RejectItemBody,
    mdo_id: str = Query(..., description="MDO ID of the logged-in MDO admin"),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Reject a specific item in an approval request with comments.
    This is used when an MDO wants to reject certain designations with specific feedback.
    """
    try:
        # Verify the request exists and belongs to this MDO
        request_stmt = select(ApprovalRequestRead).where(
            ApprovalRequestRead.id == body.request_id,
            ApprovalRequestRead.mdo_id == mdo_id
        )
        request_result = await db.execute(request_stmt)
        request = request_result.scalar_one_or_none()

        if not request:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval request not found or access denied"
            )

        if request.status != "IN_REVIEW":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot reject item in request with status '{request.status}'. Must be 'IN_REVIEW'."
            )

        # Verify the item exists and belongs to this request
        item_stmt = select(ApprovalRequestItemRead).where(
            ApprovalRequestItemRead.id == body.item_id,
            ApprovalRequestItemRead.approval_request_id == body.request_id
        )
        item_result = await db.execute(item_stmt)
        item = item_result.scalar_one_or_none()

        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval request item not found"
            )

        if item.status == "REJECTED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Item is already rejected"
            )

        # Reject the item with comment
        await db.execute(
            update(ApprovalRequestItemRead)
            .where(ApprovalRequestItemRead.id == body.item_id)
            .values(
                status=text("'REJECTED'::approval_status_enum"),
                reviewer_comments=body.rejection_comment,
                rejected_at=datetime.now(timezone.utc)
            )
        )

        # Check if we need to update the overall request status
        all_items_result = await db.execute(
            select(ApprovalRequestItemRead).where(
                ApprovalRequestItemRead.approval_request_id == body.request_id
            )
        )
        all_items = all_items_result.scalars().all()
        
        # Count statuses
        pending_count = sum(1 for item in all_items if item.status == "PENDING")
        approved_count = sum(1 for item in all_items if item.status == "APPROVED")
        rejected_count = sum(1 for item in all_items if item.status == "REJECTED")

        # Update request status based on item statuses
        if pending_count == 0:  # No pending items left
            if approved_count > 0 and rejected_count > 0:
                # Mixed results - keep as approved if any items were approved
                new_status = "approved"
            elif rejected_count > 0 and approved_count == 0:
                # All items rejected
                new_status = "rejected"
                await db.execute(
                    update(ApprovalRequestRead)
                    .where(ApprovalRequestRead.id == body.request_id)
                    .values(
                        status=text("'REJECTED'::approval_status_enum"),
                        rejected_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc)
                    )
                )
            else:
                # All approved
                new_status = "approved"
                await db.execute(
                    update(ApprovalRequestRead)
                    .where(ApprovalRequestRead.id == body.request_id)
                    .values(
                        status=text("'APPROVED'::approval_status_enum"),
                        updated_at=datetime.now(timezone.utc)
                    )
                )
        else:
            # Still has pending items, keep in review
            new_status = "IN_REVIEW"

        await db.commit()

        logger.info(f"Rejected item {body.item_id} from request {body.request_id} with comment: {body.rejection_comment}")

        return {
            "message": f"Successfully rejected designation '{item.designation_name}'",
            "request_id": body.request_id,
            "item_id": body.item_id,
            "request_status": new_status,
            "rejection_comment": body.rejection_comment
        }

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"Error rejecting approval request item")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reject approval request item"
        )