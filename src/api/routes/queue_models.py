# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field
from typing import Optional

class QueueStatusResponse(BaseModel):
    queue_size: int = Field(..., description="Number of prospects currently in the queue.")
    is_paused: bool = Field(..., description="Indicates if the queue processing is paused.")

class QueueActionResponse(BaseModel):
    success: bool
    message: str
    queue_size: Optional[int] = None
