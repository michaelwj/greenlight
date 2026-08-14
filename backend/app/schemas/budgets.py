from pydantic import BaseModel, Field


class BudgetUpdate(BaseModel):
    weekly_minutes: int = Field(ge=0, le=10080)
    bucket: str = "entertainment"


class BudgetStatusRead(BaseModel):
    child_id: str
    bucket: str
    weekly_minutes: int
    used_minutes: int
    remaining_minutes: int
