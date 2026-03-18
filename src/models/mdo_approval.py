"""
MDO Approval models - mirrors approval_requests, approval_request_items, and mdo_approval tables.
This service has READ access to approval_requests/items and FULL WRITE access to mdo_approval.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from ..core.database import Base


class ApprovalRequestRead(Base):
    """
    READ-ONLY mirror of approval_requests table from cbp-tool.
    Used by MDO portal to view pending approval requests.
    """
    __tablename__ = "approval_requests"
    __table_args__ = {'extend_existing': True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    request_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    
    # Organization context
    org_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    state_center_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    department_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    state_center_name: Mapped[str] = mapped_column(String(255), nullable=False)
    department_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # MDO who should approve
    mdo_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    # Counts
    designation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # Status - uses enum from cbp-tool
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    
    # Timestamps
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    
    # Reviewer comments
    reviewer_comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relationship to items (lazy loading to avoid N+1)
    items: Mapped[List["ApprovalRequestItemRead"]] = relationship(
        "ApprovalRequestItemRead",
        back_populates="approval_request",
        lazy="selectin"
    )


class ApprovalRequestItemRead(Base):
    """
    READ-ONLY mirror of approval_request_items table from cbp-tool.
    Used by MDO portal to view individual designations in approval requests.
    """
    __tablename__ = "approval_request_items"
    __table_args__ = {'extend_existing': True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    approval_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Source reference
    source_role_mapping_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    
    # Designation details
    designation_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    wing_division_section: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # JSONB fields
    role_responsibilities: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    activities: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    competencies: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    sort_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    
    # iGOT portal fields
    igot_designation_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    igot_designation_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # CBP plan snapshot
    cbp_plan_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    # Item status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    
    # Reviewer comments and rejection timestamp
    reviewer_comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationship back to request
    approval_request: Mapped["ApprovalRequestRead"] = relationship(
        "ApprovalRequestRead",
        back_populates="items"
    )


class MdoApproval(Base):
    """
    FULL WRITE ACCESS - This service owns this table.
    Tracks MDO approval/rejection actions on individual designation items.
    """
    __tablename__ = "mdo_approval"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # References
    approval_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    approval_request_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("approval_request_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # MDO details
    mdo_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    # Designation details (denormalized)
    designation_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    # Plan details
    plan_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    
    # User who submitted the request
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    
    # Publish ID for tracking published approvals
    publish_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
