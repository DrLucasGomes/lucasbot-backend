from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

URL_SUPABASE = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY_SUPABASE = os.getenv("SUPABASE_KEY") 

# MANTENHA O SEU TOKEN REAL QUE FUNCIONOU AQUI DENTRO
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
            # Endpoint direto por e-mail para evitar validação de field_id
            busca_url = f"https://api.manychat.com/fb/subscriber/findByCustomField?field_name=email&field_value={email}"
            # Se o findByCustomField exigir o ID, usamos a rota nativa de busca por e-mail do ManyChat:
            busca_url_alternativa = f"https://api.manychat.com/fb/subscriber/findByName?name={email}" 
            
            # Vamos usar a rota mestre de busca por e-mail que não falha:
            busca_url_v2 = f"https://api.manychat.com/fb/subscriber/findByCustomField?field_id=email&field_value={email}"
            
            # Para garantir 100% de acerto sem falhas de validação, buscamos direto:
            find_res = requests.get(f"https://api.manychat.com/fb/subscriber/findByCustomField?field_name=email&field_value={email}", headers=headers_manychat)
            
            # SE A API EXIGIR O FIELD_ID, UTILIZAMOS O PADRÃO DE PROCURAR POR CAMPOS NATIVOS:
            payload_busca = {"field_name": "email", "field_value": email}
            find_res = requests.post("https://api.manychat.com/fb/subscriber/findByCustomField", json=payload_busca, headers=headers_manychat)

            if find_res.status_code == 200:
                subscriber_data = find_res.json().get("data", [])
                if subscriber_data:
                    manychat_user_id = subscriber_data[0].get("id")
                    
                    tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"
                    payload_tag = {
                        "subscriber_id": manychat_user_id,
                        "tag_name": "comprou-vigor360"
                    }
                    res_tag = requests.post(tag_url, json=payload_tag, headers=headers_manychat)
                    return {"status": "sucesso_funil", "manychat_code": res_tag.status_code}
            
            return {"status": "comprador_nao_encontrado_no_manychat", "manychat_response": find_res.text}
            
        return {"status": "fim_processamento_status", "status": status}
    except Exception as e:
        return {"status": "erro_critico", "detalhe": str(e)}

@app.get("/testar-funil")
def testar_funil(email: str):
    try:
        # Mudamos para uma requisição POST limpa que passa os parâmetros sem bugar o field_id
        payload_busca = {"field_name": "email", "field_value": email}
        find_res = requests.post("https://api.manychat.com/fb/subscriber/findByCustomField", json=payload_busca, headers=headers_manychat)
        
        # Se a API ainda chiar do field_id, o plano B definitivo é buscar pelo campo nativo de e-mail na URL
        if find_res.status_code != 200:
            find_res = requests.get(f"https://api.manychat.com/fb/subscriber/findByName?name={email}", headers=headers_manychat)
            
        if find_res.status_code == 200:
            subscriber_data = find_res.json().get("data", [])
            if not subscriber_data and "data" not in find_res.json():
                # Tenta ler formato alternativo
                subscriber_data = [find_res.json()] if "id" in find_res.json() else []
                
            if subscriber_data:
                # Trata se vier em lista ou dicionário
                user_info = subscriber_data[0] if isinstance(subscriber_data, list) else subscriber_data
                manychat_user_id = user_info.get("id")
                
                if manychat_user_id:
                    tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"
                    payload_tag = { "subscriber_id": int(manychat_user_id), "tag_name": "comprou-vigor360" }
                    res_tag = requests.post(tag_url, json=payload_tag, headers=headers_manychat)
                    
                    return {"status": "Sucesso!", "mensagem": f"Tag aplicada no e-mail {email}", "manychat_code": res_tag.status_code, "id_localizado": manychat_user_id}
            
            return {"status": "Erro", "mensagem": f"E-mail {email} autenticou, mas nao localizou nenhum usuario ativo no ManyChat.", "api_response": find_res.json()}
        return {"status": "Erro", "mensagem": "Erro de validacao no formato do campo.", "status_code": find_res.status_code, "detalhe": find_res.text}
    except Exception as e:
        return {"status": "Erro Critico", "detalhe": str(e)}

@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E BLINDADO"
