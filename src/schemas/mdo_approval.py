"""
Pydantic schemas for MDO approval endpoints.
"""
from datetime import datetime
from typing import Optional, List, Union, Any
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, field_validator


# Request schemas
class ApproveRequestBody(BaseModel):
    """Request body for approving designations"""
    request_id: UUID = Field(..., description="ID of the approval request")
    plan_name: str = Field(..., description="Name of the CBP plan")
    due_date: datetime = Field(..., description="Due date for plan completion")


class RejectRequestBody(BaseModel):
    """Request body for rejecting designations"""
    request_id: UUID = Field(..., description="ID of the approval request")
    rejection_comment: str = Field(
        ..., 
        min_length=1,
        max_length=500,
        description="Reason for rejection (required, maximum 500 characters)"
    )

    @field_validator('rejection_comment')
    @classmethod
    def validate_rejection_comment(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Rejection comment cannot be empty')
        
        return v.strip()


class RejectItemBody(BaseModel):
    """Request body for rejecting individual item"""
    request_id: UUID = Field(..., description="ID of the approval request")
    item_id: UUID = Field(..., description="ID of the specific item to reject")
    rejection_comment: str = Field(
        ..., 
        min_length=1,
        max_length=500,
        description="Reason for rejecting this specific item (required, maximum 500 characters)"
    )

    @field_validator('rejection_comment')
    @classmethod
    def validate_rejection_comment(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Rejection comment cannot be empty')
        
        return v.strip()


# Response schemas
class ApprovalRequestItemSchema(BaseModel):
    """Schema for individual approval request item (designation)"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    designation_name: str
    wing_division_section: Optional[str] = None
    role_responsibilities: Optional[Union[dict, list]] = None
    activities: Optional[Union[dict, list]] = None
    competencies: Optional[Union[dict, list]] = None
    igot_designation_name: Optional[str] = None
    igot_designation_id: Optional[str] = None
    cbp_plan_data: Optional[Union[dict, list]] = None
    status: Optional[str] = "pending"
    sort_order: Optional[int] = None
    reviewer_comments: Optional[str] = None
    rejected_at: Optional[datetime] = None


class ApprovalRequestListItem(BaseModel):
    """Schema for approval request in list view"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    request_name: str
    created_at: datetime
    designation_count: int
    status: str
    state_center_name: str
    department_name: Optional[str] = None


class ApprovalRequestDetail(BaseModel):
    """Schema for detailed approval request view"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    request_name: str
    created_at: datetime
    designation_count: int
    status: str
    state_center_name: str
    department_name: Optional[str] = None
    org_type: Optional[str] = None
    state_center_id: str
    department_id: Optional[str] = None
    user_id: UUID
    reviewed_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    reviewer_comments: Optional[str] = None
    items: List[ApprovalRequestItemSchema] = []


class PaginationMetadata(BaseModel):
    """Pagination metadata"""
    current_page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool


class ApprovalRequestFilters(BaseModel):
    """Applied filters"""
    search: Optional[str] = None
    status_filter: Optional[str] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None


class PaginatedApprovalRequestsResponse(BaseModel):
    """Paginated response for approval requests"""
    items: List[ApprovalRequestListItem]
    pagination: PaginationMetadata
    filters: ApprovalRequestFilters


class ApprovalActionResponse(BaseModel):
    """Response after approve/reject action"""
    message: str
    request_status: str
    items_processed: int
    item_ids: List[UUID]
    publish_id: Optional[str] = None
