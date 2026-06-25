from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

# URL do seu projeto Supabase
URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
# Puxando a chave com segurança do Render
KEY = os.getenv("SUPABASE_KEY") 

@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados = await request.json()
        
        headers = {
            "apikey": KEY, 
            "Authorization": f"Bearer {KEY}", 
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates" 
        }
        
        # O segredo está no '?on_conflict=manychat_id' no final da URL
        response = requests.post(
            f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id", 
            json=dados, 
            headers=headers
        )
        
        return {"status": "sucesso", "code": response.status_code}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E BLINDADO"
