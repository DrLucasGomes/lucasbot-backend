from fastapi import FastAPI
import requests

app = FastAPI()

# --- DADOS QUE VOCÊ JÁ CONFERIU MIL VEZES ---
URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY = "sb_secret_2uwKMoi6Z3mN1mFU1cOKqA_Unq-q5d8" # A chave secreta (service_role), não a anon!

@app.get("/")
def testar_conexao():
    # Tenta inserir um dado de teste direto
    endpoint = f"{URL}/rest/v1/leads_vigor"
    headers = {
        "apikey": KEY,
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    payload = {"nome": "TESTE_DO_DOUTOR", "email": "teste@doutor.com"}
    
    try:
        r = requests.post(endpoint, json=payload, headers=headers)
        return {
            "status_code": r.status_code,
            "resposta_do_supabase": r.text,
            "url_usada": endpoint
        }
    except Exception as e:
        return {"erro_fatal": str(e)}

@app.post("/webhook")
async def webhook(request: Request):
    # (Mantemos o webhook aqui para depois)
    return {"status": "ok"}
