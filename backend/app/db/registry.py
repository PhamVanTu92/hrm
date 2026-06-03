"""Model registry.

Importing this module imports every ORM model so that ``Base.metadata`` is
fully populated. Alembic's ``env.py`` and test setup import this to discover all
tables. Add new modules' models here.
"""

from __future__ import annotations

# noqa: F401 — imported for side effect (table registration)
from app.audit.models import AuditLog  # noqa: F401
from app.db.base import Base
from app.modules.approval.models import (  # noqa: F401
    ApprovalInstance,
    ApprovalStepInstance,
    ApprovalWorkflow,
    ApprovalWorkflowStep,
    LeaveRequest,
)
from app.modules.attendance.models import (  # noqa: F401
    AttendanceDaily,
    AttendanceDevice,
    AttendanceMonthly,
    Holiday,
    RawPunchLog,
    Shift,
)
from app.modules.auth.models import (  # noqa: F401
    LoginAttempt,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.modules.employee.models import (  # noqa: F401
    Department,
    Employee,
    EmployeeDynamicProfile,
    Position,
    ProfileCategory,
    ProfileField,
)
from app.modules.payroll.models import (  # noqa: F401
    PayrollInputValue,
    PayrollOverride,
    PayrollPeriod,
    PayrollRun,
    PayrollRunItem,
    SalaryComponent,
    SalaryComponentAssignment,
)
from app.modules.payslip.models import (  # noqa: F401
    FileAttachment,
    Payslip,
)

__all__ = ["Base"]
