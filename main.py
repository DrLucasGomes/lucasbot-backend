from fastapi import FastAPI, Request
import requests

app = FastAPI()

# --- DADOS DO SEU SUPABASE ---
SUPABASE_URL = "https://gwxcnzuwfrswhkzflaw.supabase.co"
SUPABASE_KEY = "sb_publishable_62LT85LC41akfZME_t6sPg_7hSS8CJ2" # Use a sua anon key completa aqui
# -----------------------------

@app.post("/webhook")
async def receber_dados(request: Request):
    dados = await request.json()
    
    # Envia para a tabela 'leads_vigor' no Supabase
    url = f"{SUPABASE_URL}/rest/v1/leads_vigor"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    
    # O Python pega o que o ManyChat enviou e joga no banco de dados
    response = requests.post(url, json=dados, headers=headers)
    
    return {"status": "recebido", "supabase_status": response.status_code}
