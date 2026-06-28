from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY = os.getenv("SUPABASE_KEY") 

# TOKEN DA API PÚBLICA DO MANYCHAT PARA A VALIDAÇÃO DA KIWIFY
MANYCHAT_TOKEN = "3921505:a4bbd6f7301c5fd1cc27d876f762d0bf"

headers_manychat = {
    "Authorization": f"Bearer {MANYCHAT_TOKEN}",
    "Content-Type": "application/json"
}

# SEU WEBHOOK ORIGINAL DE QUARTA-FEIRA À NOITE — INTOCADO E BRUTO
@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados = await request.json()
        
        headers = {
            "apikey": KEY, 
            "Authorization": f"Bearer {KEY}", 
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates" 
        }
        
        # Faz exatamente o envio duplo que você tinha e que dava certo
        response = requests.post(f"{URL}/rest/v1/leads_vigor", json=dados, headers=headers)
        response = requests.post(
            f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id", 
            json=dados, 
            headers=headers
        )
        
        return {"status": "sucesso", "code": response.status_code}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

# ROTA DA KIWIFY ISOLADA PARA NÃO ATRAPALHAR O SEU FLUXO DO WHATSAPP
@app.post("/kiwify")
async def webhook_kiwify(request: Request):
    try:
        dados_kiwify = await request.json()
        status = dados_kiwify.get("order_status")
        customer = dados_kiwify.get("Customer", {})
        email = customer.get("email")
        
        custom_variables = dados_kiwify.get("custom_variables", {})
        manychat_user_id = custom_variables.get("manychat_id")
        
        telefone = customer.get("mobile", "")
        if telefone:
            telefone = "".join(filter(str.isdigit, str(telefone)))

        try:
            # Envia os dados de compra da Kiwify respeitando o on_conflict da tabela
            headers_kiwify_supabase = {
                "apikey": KEY, 
                "Authorization": f"Bearer {KEY}", 
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates"
            }
            payload_supabase = {
                "nome": customer.get("name"),
                "email": email,
                "telefone": telefone,
                "status_pagamento": status,
                "produto": dados_kiwify.get("product_name"),
                "manychat_id": str(manychat_user_id).strip() if manychat_user_id else None
            }
            # Remove valores nulos para não dar conflito nas colunas do WhatsApp
            payload_limpo = {k: v for k, v in payload_supabase.items() if v is not None and v != ""}
            
            requests.post(
                f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id", 
                json=payload_limpo, 
                headers=headers_kiwify_supabase
            )
        except Exception as err_banco:
            print(f"Erro banco kiwify: {str(err_banco)}")

        if status == "approved":
            # Disparo de Tag no ManyChat pós-venda
            if manychat_user_id:
                tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"
                payload_tag = {"subscriber_id": int(manychat_user_id), "tag_name": "comprou-vigor360"}
                res_tag = requests.post(tag_url, json=payload_tag, headers=headers_manychat)
                return {"status": "sucesso_id_direto", "manychat_code": res_tag.status_code}

            payload_busca = {"field_name": "email", "field_value": email}
            find_res = requests.post("https://api.manychat.com/fb/subscriber/findByCustomField", json=payload_busca, headers=headers_manychat)
            subscriber_data = find_res.json().get("data", [])

            if not subscriber_data and telefone:
                find_res = requests.get(f"https://api.manychat.com/fb/subscriber/findByName?name={telefone}", headers=headers_manychat)
                subscriber_data = find_res.json().get("data", []) if "data" in find_res.json() else [find_res.json()]

            if subscriber_data and isinstance(subscriber_data, list) and len(subscriber_data) > 0:
                user_info = subscriber_data[0]
                uid = user_info.get("id")
                if uid:
                    tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"
                    payload_tag = {"subscriber_id": int(uid), "tag_name": "comprou-vigor360"}
                    res_tag = requests.post(tag_url, json=payload_tag, headers=headers_manychat)
                    return {"status": "sucesso_funil_busca", "manychat_code": res_tag.status_code}
            
            return {"status": "comprador_nao_encontrado_no_manychat"}
            
        return {"status": "fim_processamento_status", "status": status}
    except Exception as e:
        return {"status": "erro_critico", "detalhe": str(e)}

@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E BLINDADO"
