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
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=256)
class SessionInput(BaseModel):
    token_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
class SessionCreate(SessionInput):
    user_id: str
    expires_at: datetime
class SessionRotate(SessionInput):
    new_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_at: datetime
