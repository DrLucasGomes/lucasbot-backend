from fastapi import FastAPI, Request
import requests

app = FastAPI()

# --- DADOS DO SEU SUPABASE ---
SUPABASE_URL = "https://gwxcnczuwfrswhkzflaw.supabase.co" 
SUPABASE_KEY = "sb_publishable_62LT85LC41akfZME_t6sPg_7hSS8CJ2" 
# -----------------------------

@app.post("/webhook")
async def receber_dados(request: Request):
    try:
        dados = await request.json()
        
        url = f"{SUPABASE_URL}/rest/v1/leads_vigor"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        
        response = requests.post(url, json=dados, headers=headers)
        
        # ESSA LINHA É O NOSSO RAIO-X:
        check_chave = SUPABASE_KEY[:5] # Pega os 5 primeiros caracteres
        
        return {
            "status": "verificando", 
            "supabase_status": response.status_code,
            "inicio_da_chave_no_servidor": check_chave,
            "erro_do_supabase": response.text
        }
    except Exception as e:
        return {"status": "erro", "mensagem": str(e)}status_code}
