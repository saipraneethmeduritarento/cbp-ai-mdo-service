"""
Helper for calling the external CBP plan create API.
"""
from datetime import date
from typing import List
import uuid as _uuid

import httpx
from fastapi import HTTPException

from ..core.configs import settings
from ..core.logger import logger

CBP_CREATE_URL = "https://mdo.igotkarmayogi.gov.in/apis/proxies/v8/cbplan/v2/create"


def extract_content_ids(cbp_plan_data_list: list) -> List[str]:
    """
    Extract deduplicated do_ content identifiers from a cbp_plan_data value.

    cbp_plan_data shape (list with one object):
    [
      {
        "selected_courses": [
          {"identifier": "do_114...", ...},
          ...
        ],
        ...
      }
    ]
    """
    seen: set = set()
    content_ids: List[str] = []

    records = cbp_plan_data_list if isinstance(cbp_plan_data_list, list) else [cbp_plan_data_list]

    for record in records:
        for course in record.get("selected_courses", []):
            identifier = course.get("identifier")
            if identifier and identifier not in seen:
                seen.add(identifier)
                content_ids.append(identifier)

    return content_ids


async def call_cbp_create(
    token: str,
    org_id: str,
    plan_name: str,
    due_date: date,
    designations: List[str],
    content_ids: List[str],
    is_apar: bool = False,
) -> str:
    """
    POST to the CBP plan create API and return the publish_id string.

    Raises HTTPException(502) on any network or API failure so the caller
    can abort before writing to the database.

    Args:
        token:        Raw Bearer token to forward in the Authorization header.
        org_id:       state_center_id from the approval request (maps to orgIdList).
        plan_name:    CBP plan name entered by the MDO admin.
        due_date:     Plan completion due date (formatted as YYYY-MM-DD).
        designations: List of designation names (igot_designation_name or designation_name).
        content_ids:  Deduplicated list of do_ course identifiers.
        is_apar:      Whether this is an APAR plan.

    Returns:
        publish_id string from result.id in the API response.
    """
    payload = {
        "request": {
            "orgIdList": [org_id],
            "comment": f"{plan_name} published via MDO portal",
            "contentList": content_ids,
            "contentType": "Course",
            "contextData": {
                "accessControl": {
                    "userGroups": [
                        {
                            "userGroupName": "User Group 1",
                            "userGroupCriteriaList": [
                                {
                                    "criteriaKey": "designation",
                                    "criteriaValue": designations,
                                }
                            ],
                        }
                    ],
                    "version": 1,
                }
            },
            "endDate": due_date.strftime("%Y-%m-%d"),
            "isApar": is_apar,
            "name": plan_name,
        }
    }

    logger.info(
        f"Calling CBP create API | org_id={org_id} | plan={plan_name} | "
        f"courses={len(content_ids)} | designations={len(designations)}"
    )

    if settings.CBP_API_KEY:
        mock_id = str(_uuid.uuid4())
        logger.warning(
            f"CBP_API_KEY=true — skipping real API call, returning dummy publish_id={mock_id}"
        )
        return mock_id

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                CBP_CREATE_URL,
                json=payload,
                headers={
                    "x-authenticated-user-token": token,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
            resp.raise_for_status()

        except httpx.HTTPStatusError as e:
            logger.error(
                f"CBP API HTTP error: {e.response.status_code} | body={e.response.text}"
            )
            raise HTTPException(
                status_code=502,
                detail=f"CBP API returned an error ({e.response.status_code}). "
                       "Approval was not saved.",
            )
        except httpx.RequestError as e:
            logger.error(f"CBP API unreachable: {str(e)}")
            raise HTTPException(
                status_code=502,
                detail="CBP API is unreachable. Approval was not saved.",
            )

    cbp_data = resp.json()
    publish_id = cbp_data.get("result", {}).get("id")

    if not publish_id:
        logger.error(f"CBP API response missing result.id: {cbp_data}")
        raise HTTPException(
            status_code=502,
            detail="CBP API did not return a plan ID. Approval was not saved.",
        )

    logger.info(f"CBP plan created | publish_id={publish_id}")
    return publish_id
