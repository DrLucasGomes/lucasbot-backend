from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY = os.getenv("SUPABASE_KEY") 

headers_supabase = {
    "apikey": KEY, 
    "Authorization": f"Bearer {KEY}", 
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates" 
}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados = await request.json()
        response = requests.post(
            f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id", 
            json=dados, 
            headers=headers_supabase
        )
        return {"status": "sucesso", "code": response.status_code}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

@app.post("/kiwify")
async def webhook_kiwify(request: Request):
    try:
        dados_kiwify = await request.json()
        
        status = dados_kiwify.get("order_status")
        customer = dados_kiwify.get("Customer", {})
        
        telefone = customer.get("mobile", "")
        if telefone:
            telefone = "".join(filter(str.isdigit, str(telefone)))

        payload_supabase = {
            "nome": customer.get("name"),
            "email": customer.get("email"),
            "telefone": telefone,
            "status_pagamento": status,
            "produto": dados_kiwify.get("product_name"),
            "manychat_id": str(dados_kiwify.get("order_id"))
        }
        
        # Faz a chamada ao Supabase
        response = requests.post(
            f"{URL}/rest/v1/leads_vigor", 
            json=payload_supabase, 
            headers=headers_supabase
        )
        
        # Mostra o erro real do Supabase nos logs do Render para podermos ler
        print(f"STATUS SUPABASE: {response.status_code}")
        print(f"RESPOSTA SUPABASE: {response.text}")
        
        # Se der erro no Supabase, repassa o status real para sabermos
        if response.status_code not in [200, 201]:
            return {"status": "erro_no_supabase", "supabase_code": response.status_code, "detalhe": response.text}
        
        return {"status": "sucesso", "supabase_code": response.status_code}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E BLINDADO"
