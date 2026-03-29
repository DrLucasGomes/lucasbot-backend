from fastapi import FastAPI, Request
import requests

app = FastAPI()

# Configurações do Supabase (Mantenha as suas)
URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY = "sb_secret_2uwKMoi6Z3mN1mFU1cOKqA_Unq-q5d8" 

@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados = await request.json()
        
        # O SEGREDO ESTÁ AQUI: "resolution=merge-duplicates"
        # Isso diz ao Supabase: "Se o ID já existe, apenas atualize os dados"
        headers = {
            "apikey": KEY, 
            "Authorization": f"Bearer {KEY}", 
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        }
        
        # Envia para o Supabase
        response = requests.post(f"{URL}/rest/v1/leads_vigor", json=dados, headers=headers)
        
        # Se o banco de dados reclamar, pegamos o detalhe
        if response.status_code >= 400:
            return {"status": "erro_banco", "detalhe": response.text}

        return {"status": "sucesso"}
        
    except Exception as e:
        return {"status": "erro_script", "detalhe": str(e)}

@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE"
