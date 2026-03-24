from fastapi import FastAPI, Request
import requests

app = FastAPI()

# --- USE A URL E A KEY QUE DERAM O ERRO 400 ---
URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY = "sb_secret_2uwKMoi6Z3mN1mFU1cOKqA_Unq-q5d8" 

@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados = await request.json()
        headers = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
        # Tenta gravar
        requests.post(f"{URL}/rest/v1/leads_vigor", json=dados, headers=headers)
        return {"status": "sucesso"}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

@app.get("/")
def home():
    return "ONLINE"
