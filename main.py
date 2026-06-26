from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

# Configurações das Chaves (Puxadas com segurança do Render)
URL_SUPABASE = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY_SUPABASE = os.getenv("SUPABASE_KEY") 
MANYCHAT_TOKEN = os.getenv("MANYCHAT_TOKEN")

headers_supabase = {
    "apikey": KEY_SUPABASE, 
    "Authorization": f"Bearer {KEY_SUPABASE}", 
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates" # Atualiza a linha do paciente sem duplicar
}

headers_manychat = {
    "Authorization": f"Bearer {MANYCHAT_TOKEN}",
    "Content-Type": "application/json"
}

# 1. ROTA EXISTENTE DO MANYCHAT
@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados = await request.json()
        response = requests.post(
            f"{URL_SUPABASE}/rest/v1/leads_vigor?on_conflict=manychat_id", 
            json=dados, 
            headers=headers_supabase
        )
        return {"status": "sucesso", "code": response.status_code}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

# 2. ROTA DA KIWIFY - ATUALIZA O BANCO COMPLETO E COMANDA O MANYCHAT
@app.post("/kiwify")
async def webhook_kiwify(request: Request):
    try:
        dados_kiwify = await request.json()
        status = dados_kiwify.get("order_status")
        customer = dados_kiwify.get("Customer", {})
        email = customer.get("email")
        
        # Limpa o telefone para deixar apenas números
        telefone = customer.get("mobile", "")
        if telefone:
            telefone = "".join(filter(str.isdigit, str(telefone)))

        # ------------------------------------------------------------
        # PASSO 1: ATUALIZA O PACIENTE NO SUPABASE COM OS DADOS DE VENDA
        # ------------------------------------------------------------
        payload_supabase = {
            "nome": customer.get("name"),
            "email": email,
            "telefone": telefone,
            "status_pagamento": status,
            "produto": dados_kiwify.get("product_name"),
            "manychat_id": str(dados_kiwify.get("order_id"))
        }
        
        # Faz o Upsert na tabela mantendo o histórico dinâmico do paciente
        res_supabase = requests.post(
            f"{URL_SUPABASE}/rest/v1/leads_vigor?on_conflict=manychat_id", 
            json=payload_supabase, 
            headers=headers_supabase
        )
        print(f"SUPABASE LOG - Status: {res_supabase.status_code}")

        # ------------------------------------------------------------
        # PASSO 2: APLICA A TAG NO MANYCHAT SE FOR COMPRA APROVADA
        # ------------------------------------------------------------
        if status == "approved":
            busca_url = f"https://api.manychat.com/fb/subscriber/findByCustomField?field_name=email&field_value={email}"
            find_res = requests.get(busca_url, headers=headers_manychat)
            
            if find_res.status_code == 200:
                subscriber_data = find_res.json().get("data", [])
                if subscriber_data:
                    manychat_user_id = subscriber_data[0].get("id")
                    
                    # Carimba a tag para salvar o cara do áudio de cobrança de 2h
                    tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"
                    payload_tag = {
                        "subscriber_id": manychat_user_id,
                        "tag_name": "comprou-vigor360"
                    }
                    
                    res_tag = requests.post(tag_url, json=payload_tag, headers=headers_manychat)
                    print(f"MANYCHAT LOG - Tag aplicada para: {email} | Status: {res_tag.status_code}")
                    
                    return {"status": "sucesso", "supabase": res_supabase.status_code, "manychat": "tag_aplicada"}
            
            print(f"Comprador {email} atualizado no banco, mas não localizado no ManyChat.")
            return {"status": "sucesso_parcial", "supabase": res_supabase.status_code, "manychat": "nao_encontrado"}
            
        return {"status": "sucesso_supabase", "supabase": res_supabase.status_code, "manychat": "ignorado_status"}
        
    except Exception as e:
        print(f"Erro crítico: {str(e)}")
        return {"status": "erro", "detalhe": str(e)}

# 3. HOME
@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E BLINDADO"
