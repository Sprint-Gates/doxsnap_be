from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, RolePermission, Permission
from app.utils.security import verify_token

METHOD_ACTION_MAP = {
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}

# Map specific endpoint patterns to their actions
# Format: {path_segment: action}
# These are checked when the default METHOD_ACTION_MAP doesn't match
ACTION_PATH_PATTERNS = {
    # Authentication & OTP
    "login": "login",
    "logout": "logout",
    "refresh": "refresh",
    "register": "register",
    "send": "send",
    "verify": "verify",
    "resend": "resend",

    # Workflow actions
    "approve": "approve",
    "reject": "reject",
    "submit": "submit",
    "cancel": "cancel",
    "complete": "complete",
    "finalize": "finalize",
    "acknowledge": "acknowledge",

    # Financial actions
    "post": "post",
    "reverse": "reverse",
    "hold": "hold",
    "void": "void",

    # Contract actions
    "activate": "activate",
    "terminate": "terminate",
    "renew": "renew",

    # Assignment actions
    "assign": "assign",
    "unassign": "unassign",

    # Transfer & movement
    "transfer": "transfer",
    "allocate": "allocate",
    "issue": "issue_item",
    "return": "return_item",

    # Inspection & validation
    "inspect": "inspect",
    "match": "match",

    # Status changes
    "toggle-status": "toggle_status",
    "set-main": "set_main",

    # Conversion
    "convert": "convert",
    "convert-to-po": "convert_to_po",

    # Import/Export
    "import": "create",
    "export": "view",
    "bulk-import": "bulk_import",
    "bulk-upload": "bulk_upload",
    "download-template": "download_template",

    # Linking
    "link": "link_invoice",
    "unlink": "unlink_invoice",
    "link-warehouse": "link_warehouse",
    "unlink-warehouse": "unlink_warehouse",
    "link-vendor": "link_vendor",

    # Special operations
    "seed": "seed",
    "reprocess": "reprocess",
    "receive": "receive",
    "send-email": "send_email",
    "replenish": "replenish",
    "close": "close",
    "generate": "generate",
    "lookup": "lookup",
    "follow-up": "follow_up",
    "calculate": "calculate_depreciation",
    "recompute": "recompute_balances",
    "recognize": "recognize",
    "unrecognize": "unrecognize",
    "three-way-match": "three_way_match",
    "clear-grni": "clear_grni",
    "upload-logo": "upload_logo",
    "forgot-password": "forgot_password",
    "reset-password": "reset_password",
}

PUBLIC_PATHS = (
    "/api/auth",
    "/api/otp",
    "/api/docs",
    "/api/health",
    "/api/plans",
    "/api/companies/register"
)


class PermissionMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        print(f"[PERMISSION] {request.method} {request.url.path}")

        # Skip non-API routes
        if not path.startswith("/api/"):
            return await call_next(request)

        # Skip public routes
        for p in PUBLIC_PATHS:
            if path.startswith(p):
                return await call_next(request)

        # Skip OPTIONS
        if request.method == "OPTIONS":
            return await call_next(request)

        # Read token
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )

        token = auth_header.split(" ")[1]
        email = verify_token(token)
        if not email:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        db: Session = next(get_db())

        try:
            user = db.query(User).filter(User.email == email).first()
            if not user:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "User not found"},
                )

            # Infer module and action from path
            # /api/branches/123 → module: branches
            # /api/purchase-orders/5/approve → module: purchase_orders, action: approve
            parts = path.replace("/api/", "").strip("/").split("/")
            print(f"Parts: {parts}")
            if not parts:
                return await call_next(request)

            module = parts[0]  # Convert kebab-case to snake_case

            # Determine action - check for specific action in path first
            action = None

            # Check if any part of the path matches a specific action pattern
            for part in parts[1:]:  # Skip module name
                part_lower = part.lower()
                if part_lower in ACTION_PATH_PATTERNS:
                    action = ACTION_PATH_PATTERNS[part_lower]
                    break

            # If no specific action found in path, use HTTP method mapping
            if not action:
                action = METHOD_ACTION_MAP.get(request.method)

            # Only check permissions if we have an action (skip if None)
            if action:
                role_permissions = (
                    db.query(RolePermission)
                    .join(Permission)
                    .filter(RolePermission.role_id == user.role_id)
                    .all()
                )

                allowed = any(
                    rp.permission.module.lower() == module.lower()
                    and rp.permission.action.lower() == action.lower()
                    for rp in role_permissions
                )

                if not allowed:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": f"Permission '{module}:{action}' not authorized"
                        },
                    )

            # Attach user for later use (optional)
            request.state.user = user

            return await call_next(request)

        finally:
            db.close()
