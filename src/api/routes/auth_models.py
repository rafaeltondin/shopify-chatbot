# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field
from typing import Optional

class Token(BaseModel):
    access_token: str
    token_type: str

class LoginRequest(BaseModel):
    username: str = Field(..., description="Username for login.")
    password: str = Field(..., description="Password for login.")

class LoginResponse(BaseModel):
    success: bool = Field(True)
    message: str = Field("Login successful.", description="Status message.")
    token: Optional[Token] = None

class ErrorResponse(BaseModel):
    detail: str = Field(..., description="Detailed error message.")
