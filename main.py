from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from dotenv import load_dotenv
import httpx
from brevo import Brevo
from brevo.transactional_emails import (
    SendTransacEmailRequestSender,
    SendTransacEmailRequestToItem,
)
from brevo.core.api_error import ApiError
import random
from datetime import datetime, timedelta

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Keys
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_NAME = os.getenv("SENDER_NAME", "Govt Scheme Checker")

client = Brevo(api_key=BREVO_API_KEY)

# --- 1. REAL OTP (Brevo) ---
otp_store = {}

class OTPRequest(BaseModel):
    email: str

class OTPVerifyRequest(BaseModel):
    email: str
    otp: str

@app.post("/api/v1/generate-otp")
async def generate_otp(req: OTPRequest):
    if not BREVO_API_KEY:
        raise HTTPException(status_code=500, detail="Brevo API Key missing")

    otp_code = str(random.randint(100000, 999999))
    expiry_time = datetime.now() + timedelta(minutes=5)
    otp_store[req.email] = {"otp": otp_code, "expires": expiry_time}

    subject = "🔐 Your OTP for Govt Scheme Checker"
    html_content = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
        <h2 style="color: #0b3d91;">🔐 Login Verification</h2>
    
        <h1 style="background: #f4f6f9; padding: 15px; text-align: center; letter-spacing: 5px; border-radius: 8px; color: #138808;">{otp_code}</h1>
        <p style="color: #666; font-size: 12px;">This OTP is valid for 5 minutes.</p>
    </div>
    """

    try:
        client.transactional_emails.send_transac_email(
            subject=subject,
            html_content=html_content,
            sender=SendTransacEmailRequestSender(email=SENDER_EMAIL, name=SENDER_NAME),
            to=[SendTransacEmailRequestToItem(email=req.email, name="User")],
        )
        return {"status": "success", "message": "OTP sent successfully"}
    except ApiError as e:
        raise HTTPException(status_code=500, detail=f"Brevo Error: {e.body}")

@app.post("/api/v1/verify-otp")
async def verify_otp(req: OTPVerifyRequest):
    stored_data = otp_store.get(req.email)
    
    if not stored_data:
        raise HTTPException(status_code=400, detail="No OTP requested for this email.")
    if datetime.now() > stored_data["expires"]:
        raise HTTPException(status_code=400, detail="OTP has expired.")
    if stored_data["otp"] != req.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP.")
    
    del otp_store[req.email]
    return {"status": "success", "message": "OTP verified successfully"}

# --- 2. AI CHAT (OpenRouter) ---
class UserQuery(BaseModel):
    query: str
    age: int
    income: int
    language: str = "English"

@app.post("/api/v1/chat")
async def chat_with_agent(user_data: UserQuery):
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API Key missing")

    context = "1. PM-Kisan: Farmers support. 2. Ayushman Bharat: Health insurance."
    system_prompt = f"""
    You are an AI Assistant. User: Age {user_data.age}, Income {user_data.income}.
    Data: {context}
    Return ONLY JSON array: [{{"name": "Scheme", "match": 95, "reason": "Why", "link": "url"}}]
    """

    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                json={
                    "model": "openai/gpt-3.5-turbo",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_data.query}
                    ]
                },
                timeout=30.0
            )
            result = response.json()
            ai_text = result['choices'][0]['message']['content']
            return {"status": "success", "agent_response": ai_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- 3. EMAIL REMINDER (Brevo) ---
class EmailRequest(BaseModel):
    email: str
    scheme_name: str
    days_left: int
    apply_link: str

@app.post("/api/v1/send-reminder")
async def send_reminder(req: EmailRequest):
    if not BREVO_API_KEY:
        raise HTTPException(status_code=500, detail="Brevo API Key missing")

    if req.days_left <= 1:
        subject = f"🚨 Today is the Last Day for {req.scheme_name}!"
        html_content = f"<h2>Today is the Last Day!</h2><p>Apply for {req.scheme_name} now: <a href='{req.apply_link}'>Apply</a></p>"
    else:
        subject = f"⏳ Alert: Only {req.days_left} Days Left for {req.scheme_name}"
        html_content = f"<h2>Deadline Approaching!</h2><p>Only {req.days_left} days left for {req.scheme_name}. <a href='{req.apply_link}'>Apply</a></p>"

    try:
        client.transactional_emails.send_transac_email(
            subject=subject,
            html_content=html_content,
            sender=SendTransacEmailRequestSender(email=SENDER_EMAIL, name=SENDER_NAME),
            to=[SendTransacEmailRequestToItem(email=req.email, name="User")],
        )
        return {"status": "success", "message": "Email sent successfully"}
    except ApiError as e:
        raise HTTPException(status_code=500, detail=f"Brevo Error: {e.body}")