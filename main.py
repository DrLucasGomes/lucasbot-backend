from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

URL_SUPABASE = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY_SUPABASE = os.getenv("SUPABASE_KEY") 

# COLA O SEU TOKEN DA API PÚBLICA QUE FUNCIONOU BEM AQUI DENTRO
MANYCHAT_TOKEN = "3921505:a4bbd6f7301c5fd1cc27d876f762d0bf"

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
        
        # Tenta pegar o ID se ele vier perdido em alguma variável customizada
        custom_variables = dados_kiwify.get("custom_variables", {})
        manychat_user_id = custom_variables.get("manychat_id")
        
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
            # SE TIVERMOS O ID DIRETO, CORRE PARA APLICAÇÃO BRUTA DA TAG
            if manychat_user_id:
                tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"
                payload_tag = {"subscriber_id": int(manychat_user_id), "tag_name": "comprou-vigor360"}
                res_tag = requests.post(tag_url, json=payload_tag, headers=headers_manychat)
                return {"status": "sucesso_id_direto", "manychat_code": res_tag.status_code}

            # SE NÃO TIVER ID, FAZ O COMBINADO PLANO B (EMAIL OU TELEFONE)
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

# ROTA RECONFIGURADA PARA ACEITAR TESTE DIRETO POR ID (VIA NAVEGADOR)
@app.get("/testar-id")
def testar_id(id_user: int):
    try:
        tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"
        payload_tag = { "subscriber_id": id_user, "tag_name": "comprou-vigor360" }
        res_tag = requests.post(tag_url, json=payload_tag, headers=headers_manychat)
        return {
            "status": "Comando Enviado!", 
            "manychat_code": res_tag.status_code, 
            "mensagem": f"Tag disparada direto para o ID {id_user}", 
            "resposta_manychat": res_tag.json()
        }
    except Exception as e:
        return {"status": "Erro", "detalhe": str(e)}

@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E BLINDADO"
