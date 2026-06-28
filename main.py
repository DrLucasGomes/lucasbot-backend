from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY = os.getenv("SUPABASE_KEY") 

# TOKEN DA API PÚBLICA DO MANYCHAT
MANYCHAT_TOKEN = "3921505:a4bbd6f7301c5fd1cc27d876f762d0bf"

headers_manychat = {
    "Authorization": f"Bearer {MANYCHAT_TOKEN}",
    "Content-Type": "application/json"
}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados_brutos = await request.json()
        
        mc_id = dados_brutos.get("manychat_id")
        if not mc_id:
            return {"status": "erro", "detalhe": "manychat_id nao encontrado"}
            
        mc_id_str = str(mc_id).strip()

        # REMOVE TUDO QUE FOR NULO, VAZIO OR STRING "NONE"
        # Isso impede que o ManyChat limpe o banco na segunda etapa
        dados_limpos = {}
        for k, v in dados_brutos.items():
            if v is not None and str(v).strip() != "" and str(v).lower() != "none":
                dados_limpos[k] = v

        # Garante o ID correto no payload final
        dados_limpos["manychat_id"] = mc_id_str

        headers_supabase = {
            "apikey": KEY, 
            "Authorization": f"Bearer {KEY}", 
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        }
        
        # Faz o upsert direto com os dados limpos
        url_upsert = f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id"
        response = requests.post(url_upsert, json=dados_limpos, headers=headers_supabase)
        
        return {"status": "sucesso", "code": response.status_code}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

# ROTA DA KIWIFY - TOTALMENTE ISOLADA E LIMPA
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
            
            # Limpeza também na rota da Kiwify
            payload_limpo = {k: v for k, v in payload_supabase.items() if v is not None and str(v).strip() != ""}
            
            requests.post(
                f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id", 
                json=payload_limpo, 
                headers=headers_kiwify_supabase
            )
        except Exception as err_banco:
            print(f"Erro banco kiwify: {str(err_banco)}")

        if status == "approved":
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
