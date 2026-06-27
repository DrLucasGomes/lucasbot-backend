from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

URL_SUPABASE = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY_SUPABASE = os.getenv("SUPABASE_KEY") 

# MANTENHA O SEU TOKEN REAL AQUI DENTRO
MANYCHAT_TOKEN = "COLE_AQUI_O_SEU_TOKEN_DO_MANYCHAT"

headers_supabase = {
    "apikey": KEY_SUPABASE, 
    "Authorization": f"Bearer {KEY_SUPABASE}", 
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

headers_manychat = {
    "Authorization": f"Bearer {MANYCHAT_TOKEN}",
    "Content-Type": "application/json"
}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados = await request.json()
        response = requests.post(
            f"{URL_SUPABASE}/rest/v1/leads_vigor?on_conflict=email", 
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
        email = customer.get("email")
        
        telefone = customer.get("mobile", "")
        if telefone:
            telefone = "".join(filter(str.isdigit, str(telefone)))

        try:
            payload_supabase = {
                "nome": customer.get("name"),
                "email": email,
                "telefone": telefone,
                "status_pagamento": status,
                "produto": dados_kiwify.get("product_name")
            }
            res_supabase = requests.post(
                f"{URL_SUPABASE}/rest/v1/leads_vigor?on_conflict=email", 
                json=payload_supabase, 
                headers=headers_supabase
            )
            print(f"SUPABASE STATUS LOG: {res_supabase.status_code}")
        except Exception as err_banco:
            print(f"Erro banco: {str(err_banco)}")

        if status == "approved":
            # Tenta buscar por E-mail primeiro
            payload_busca = {"field_name": "email", "field_value": email}
            find_res = requests.post("https://api.manychat.com/fb/subscriber/findByCustomField", json=payload_busca, headers=headers_manychat)
            subscriber_data = find_res.json().get("data", [])

            # Se não achar por e-mail, busca pelo Telefone (Plano B Blindado)
            if not subscriber_data and telefone:
                find_res = requests.get(f"https://api.manychat.com/fb/subscriber/findByName?name={telefone}", headers=headers_manychat)
                subscriber_data = find_res.json().get("data", []) if "data" in find_res.json() else [find_res.json()]

            if subscriber_data and isinstance(subscriber_data, list) and len(subscriber_data) > 0:
                user_info = subscriber_data[0]
                manychat_user_id = user_info.get("id")
                
                if manychat_user_id:
                    tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"
                    payload_tag = {
                        "subscriber_id": int(manychat_user_id),
                        "tag_name": "comprou-vigor360"
                    }
                    res_tag = requests.post(tag_url, json=payload_tag, headers=headers_manychat)
                    return {"status": "sucesso_funil", "manychat_code": res_tag.status_code}
            
            return {"status": "comprador_nao_encontrado", "email_tentado": email, "tel_tentado": telefone}
            
        return {"status": "fim_processamento_status", "status": status}
    except Exception as e:
        return {"status": "erro_critico", "detalhe": str(e)}

# NOVA ROTA DE TESTE QUE ACEITA TELEFONE OU E-MAIL
@app.get("/testar-funil")
def testar_funil(dado: str):
    try:
        # Tenta buscar assumindo que é e-mail
        payload_busca = {"field_name": "email", "field_value": dado}
        find_res = requests.post("https://api.manychat.com/fb/subscriber/findByCustomField", json=payload_busca, headers=headers_manychat)
        subscriber_data = find_res.json().get("data", [])
        
        # Se falhar ou se for número, busca pelo campo de telefone/nome
        if not subscriber_data:
            dado_limpo = "".join(filter(str.isdigit, dado))
            find_res = requests.get(f"https://api.manychat.com/fb/subscriber/findByName?name={dado_limpo}", headers=headers_manychat)
            if find_res.status_code == 200:
                res_json = find_res.json()
                subscriber_data = res_json.get("data", []) if isinstance(res_json, dict) and "data" in res_json else [res_json]

        if subscriber_data and len(subscriber_data) > 0 and subscriber_data[0].get("id"):
            manychat_user_id = subscriber_data[0].get("id")
            
            tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"
            payload_tag = { "subscriber_id": int(manychat_user_id), "tag_name": "comprou-vigor360" }
            res_tag = requests.post(tag_url, json=payload_tag, headers=headers_manychat)
            
            return {"status": "Sucesso!", "mensagem": f"Tag aplicada no lead {dado}", "manychat_code": res_tag.status_code, "id_manychat": manychat_user_id}
            
        return {"status": "Erro", "mensagem": f"Nao localizou o usuario por e-mail ou telefone: {dado}"}
    except Exception as e:
        return {"status": "Erro Critico", "detalhe": str(e)}

@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E BLINDADO"
