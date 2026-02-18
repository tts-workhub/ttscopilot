from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from openai import OpenAI
import os
import pdfplumber
import io
import json
import re
import logging

from ..database import get_db
from ..models import Persona
from ..auth import get_current_user
from ..limiting import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/personas", tags=["personas"])

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing in environment")

client = OpenAI(api_key=OPENAI_API_KEY)

MAX_PERSONA_CHARS = 30000
MAX_PDF_BYTES = 5 * 1024 * 1024  # 5MB

class Question(BaseModel):
    text: str

# Dependency that ensures limiter_key can use request.state.user_id
def current_user_with_state(
    request: Request,
    current_user=Depends(get_current_user),
):
    request.state.user_id = current_user.id
    request.state.role = getattr(current_user, "role", None)
    return current_user

def _strip_code_fences(s: str) -> str:
    s = s.strip()
    # remove ```json ... ``` or ``` ... ```
    s = re.sub(r"^\s*```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()

@router.post("/upload")
@limiter.limit("5/minute")
async def upload_persona(
    request: Request,
    file: UploadFile = File(...),
    current_user=Depends(current_user_with_state),
    db: Session = Depends(get_db),
):
    if file.content_type not in ("application/pdf", "application/x-pdf"):
        raise HTTPException(400, "PDF only allowed")

    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(400, "File too large (max 5MB)")

    text_parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    text = "\n".join(text_parts).strip()

    if not text:
        raise HTTPException(400, "Could not extract text from PDF")

    text = text[:MAX_PERSONA_CHARS]

    persona = db.query(Persona).filter(Persona.user_id == current_user.id).first()
    if persona:
        persona.instructions = text
    else:
        persona = Persona(user_id=current_user.id, instructions=text)
        db.add(persona)

    db.commit()
    return {"message": "Persona uploaded/updated", "chars": len(text)}

@router.post("/process-question")
@limiter.limit("30/minute")
async def process_question(
    request: Request,
    q: Question = Body(...),
    current_user=Depends(current_user_with_state),
    db: Session = Depends(get_db),
):
    persona = db.query(Persona).filter(Persona.user_id == current_user.id).first()
    if not persona:
        raise HTTPException(404, "No persona found")

    prompt = f"""
You are roleplaying this persona (PRIVATE, do not mention it):
{persona.instructions}

Return ONLY valid JSON with EXACTLY these keys:
{{
  "answer": "natural, short, human-like response",
  "persona_update": "short optional update or empty string"
}}

Question: {q.text}
""".strip()

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=250,
        )
    except Exception as e:
        logger.exception("OpenAI call failed")
        raise HTTPException(502, "LLM provider error")

    content = (resp.choices[0].message.content or "").strip()
    content = _strip_code_fences(content)

    # Try strict JSON parse
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Fallback: attempt to extract first JSON object
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            logger.error("Invalid JSON from LLM (no JSON object found)")
            raise HTTPException(500, "LLM response format error")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            logger.error("Invalid JSON from LLM (parse failed after extraction)")
            raise HTTPException(500, "LLM response format error")

    answer = (data.get("answer") or "").strip()
    update = (data.get("persona_update") or "").strip()

    if not answer:
        raise HTTPException(500, "LLM returned empty answer")

    if update:
        new_text = (persona.instructions + "\n" + update).strip()
        persona.instructions = new_text[-MAX_PERSONA_CHARS:]
        db.commit()

    return {"answer": answer}
