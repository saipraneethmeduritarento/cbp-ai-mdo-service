
from fastapi import APIRouter

from .mdo_approval import router as mdo_approval_router

router = APIRouter(prefix="/v1")

router.include_router(mdo_approval_router)
