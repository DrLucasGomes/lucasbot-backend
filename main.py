from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

# --- DADOS DO SEU SUPABASE ---
# Verifique se o link termina com .co (sem barra no final)
URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
# Cole a chave ANON inteira entre as aspas abaixo
KEY = "sb_publishable_62LT85LC41akfZME_t6sPg_7hSS8CJ2" 
# -----------------------------

@app.get("/")
def home():
    return {"status": "Doutor, o servidor está ONLINE!"}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados = await request.json()
        headers = {
            "apikey": KEY,
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        # Envia para a tabela leads_vigor
        res = requests.post(f"{URL}/rest/v1/leads_vigor", json=dados, headers=headers)
        return {"status": "sucesso", "supabase_code": res.status_code}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}
