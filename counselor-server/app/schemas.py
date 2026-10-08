from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
class StudentInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    classroom: str = Field(min_length=1, max_length=40)
    referral: str = Field(default="", max_length=4000)
    @field_validator("name", "classroom")
    @classmethod
    def nonblank(cls, v):
        if not v.strip(): raise ValueError("שדה חובה")
        return v.strip()
class MeetingInput(BaseModel):
    template: str = Field(default="followup", pattern=r"^(first|followup|parents)$")
    topic: str = Field(default="other", pattern=r"^(social|learning|emotional|attendance|family|other)$")
    subjects: str = Field(default="", max_length=4000)
    decisions: list[str] = Field(default_factory=list, max_length=30)
    next_steps: str = Field(default="", max_length=4000)
    expected_version: int = Field(default=1, ge=1)
    @field_validator("decisions")
    @classmethod
    def decisions_valid(cls, v):
        if any(len(x)>1000 for x in v): raise ValueError("החלטה אינה תקינה")
        return [x.strip() for x in v if x.strip()]
    starts_at: datetime
    notes: str = Field(default="", max_length=20000)
    summary: str = Field(default="", max_length=10000)
    ai_assisted: bool = False
    consent_recorded: bool = False
    ai_reviewed: bool = False
    @model_validator(mode="after")
    def require_ai_review(self):
        if self.ai_assisted and not (self.consent_recorded and self.ai_reviewed):
            raise ValueError("נדרשים הסכמה ואישור טיוטת AI")
        return self
    @field_validator("starts_at")
    @classmethod
    def timezone_required(cls, v):
        if v.tzinfo is None: raise ValueError("נדרש אזור זמן")
        return v
class LoginInput(BaseModel):
    otp: str = Field(default="", max_length=64)
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=256)
class SessionInput(BaseModel):
    token_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
class SessionCreate(SessionInput):
    session_version: int = 0
    user_id: str
    expires_at: datetime
class SessionRotate(SessionInput):
    new_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_at: datetime
