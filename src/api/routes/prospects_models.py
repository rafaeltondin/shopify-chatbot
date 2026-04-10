# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict, Any

class ProspectRequest(BaseModel):
    numbers_with_names: Optional[str] = Field(None, description="Comma or newline-separated phone numbers and optional names (e.g., 'número,nome\\n5511xxxx,João Silva'). Accepts the raw text from textarea.")
    numbers: Optional[List[str]] = Field(None, description="Alternative: Array of phone numbers without names.")

    @model_validator(mode='before')
    def check_at_least_one_field(cls, data):
        if isinstance(data, dict):
            if not data.get('numbers_with_names') and not data.get('numbers'):
                raise ValueError("Either 'numbers_with_names' or 'numbers' must be provided")
            if data.get('numbers_with_names') and isinstance(data['numbers_with_names'], dict):
                # Handle case where frontend sends {numbers_with_names: "text"}
                data['numbers_with_names'] = data['numbers_with_names'].get('numbers_with_names', '')
        return data

class ProspectResponse(BaseModel):
    message: str = Field(..., description="Result message.")
    submitted_count: int = Field(..., description="Number of valid numbers submitted.")
    initial_queue_size: int = Field(..., description="Queue size before submission.")
    current_queue_size: int = Field(..., description="Estimated queue size after submission.")

class ProspectListItem(BaseModel):
    jid: str
    name: Optional[str] = Field(None, description="Name of the prospect.")
    current_stage: int
    status: str
    llm_paused: bool = Field(False, description="Indicates if LLM responses are paused for this prospect")
    last_interaction_at: Optional[str] = None
    created_at: Optional[str] = None
    tags: List[str] = Field(default_factory=list, description="List of tags assigned to this prospect")

class ProspectListResponse(BaseModel):
    prospects: List[ProspectListItem]
    total_count: int

class ConversationHistoryItem(BaseModel):
    role: str
    content: str
    timestamp: Optional[str] = None
    llm_model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

class ProspectHistoryResponse(BaseModel):
    jid: str
    history: List[ConversationHistoryItem]

class ProspectLLMPauseRequest(BaseModel):
    llm_paused: bool = Field(..., description="The desired LLM pause state for the prospect.")
