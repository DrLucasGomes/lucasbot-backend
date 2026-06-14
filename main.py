from fastapi import FastAPI, Request
import requests

app = FastAPI()

# Suas configurações
URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY = "sb_secret_2uwKMoi6Z3mN1mFU1cOKqA_Unq-q5d8" 

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
        
        # Envio direto para o banco
        response = requests.post(f"{URL}/rest/v1/leads_vigor", json=dados, headers=headers)
        
        return {"status": "sucesso", "code": response.status_code}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE"
