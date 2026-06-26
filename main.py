from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

# URL do seu projeto Supabase
URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
# Puxando a chave com segurança do Render
KEY = os.getenv("SUPABASE_KEY") 

# HEADERS PADRÃO PARA O SUPABASE
headers_supabase = {
    "apikey": KEY, 
    "Authorization": f"Bearer {KEY}", 
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates" 
}

# 1. ROTA EXISTENTE DO MANYCHAT (MANTIDA IGUAL)
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

# 2. NOVA ROTA EXCLUSIVA PARA A KIWIFY
@app.post("/kiwify")
async def webhook_kiwify(request: Request):
    try:
        dados_kiwify = await request.json()
        
        # Extrai o status da ordem e os dados do cliente do padrão Kiwify
        status = dados_kiwify.get("order_status")
        customer = dados_kiwify.get("Customer", {})
        
        # Limpa e formata o telefone que vem da Kiwify
        telefone = customer.get("mobile", "")
        if telefone:
            # Garante que caracteres extras sumam, deixando apenas números
            telefone = "".join(filter(str.isdigit, str(telefone)))

        # Monta o payload organizado para a sua tabela 'leads_vigor'
        payload_supabase = {
            "nome": customer.get("name"),
            "email": customer.get("email"),
            "telefone": telefone,
            "status_pagamento": status,
            "produto": dados_kiwify.get("product_name"),
            "manychat_id": dados_kiwify.get("order_id") # Usando o ID da ordem como fallback de identificação única
        }
        
        # Envia os dados tratados para o Supabase
        response = requests.post(
            f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id", 
            json=payload_supabase, 
            headers=headers_supabase
        )
        
        return {"status": "sucesso", "supabase_code": response.status_code}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

# 3. ROTA DE VERIFICAÇÃO (HOME)
@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E BLINDADO"
