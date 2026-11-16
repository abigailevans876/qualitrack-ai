from fastapi import Header, HTTPException
from src.models import Role


def get_current_user(
    x_user_id: str = Header(..., alias="X-User-Id"),
    x_user_role: str = Header(..., alias="X-User-Role"),
) -> dict:
    try:
        role = Role(x_user_role)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid role claim")
    return {"user_id": x_user_id, "role": role}


def require_role(*allowed_roles: Role):
    def checker(user: dict) -> dict:
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"RBAC Denial (NFR-06): Role '{user['role'].value}' is not authorized for this endpoint.",
            )
        return user
    return checker