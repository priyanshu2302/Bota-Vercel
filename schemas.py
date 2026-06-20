from pydantic import BaseModel
from typing import Optional

class Appointment(BaseModel):
    name: str
    age: Optional[str] = ""
    date: str
    time: str
    service: Optional[str] = "General Consultation"

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    conversation_history: Optional[list[ChatMessage]] = []