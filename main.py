from fastapi import FastAPI, Request
import requests

# 1. Declaramos o app primeiro
app = FastAPI()

# 2. Suas configurações
URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY = "sb_secret_2uwKMoi6Z3mN1mFU1cOKqA_Unq-q5d8" 

# 3. Definimos a rota de recebimento
@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados = await request.json()
        
        # Tentamos pegar o ID do usuário de diferentes formas que o ManyChat envia
        whatsapp_id = dados.get("whatsapp_id") or dados.get("id") or dados.get("user_id")
        
        if not whatsapp_id:
            return {"status": "erro", "detalhe": "ID do WhatsApp não encontrado"}
        
        headers = {
            "apikey": KEY, 
            "Authorization": f"Bearer {KEY}", 
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates" 
        }
        
        # Enviamos para a tabela leads_vigor
        response = requests.post(f"{URL}/rest/v1/leads_vigor", json=dados, headers=headers)
        
        if response.status_code >= 400:
            return {"status": "erro_banco", "detalhe": response.text}

        return {"status": "sucesso"}
        
    except Exception as e:
        return {"status": "erro_script", "detalhe": str(e)}

# 4. Rota de teste para ver se o bot está online
@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE"
