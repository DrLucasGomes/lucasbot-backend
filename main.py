from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

URL_SUPABASE = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY_SUPABASE = os.getenv("SUPABASE_KEY") 

# COLA O SEU TOKEN DO MANYCHAT DIRETO DENTRO DAS ASPAS ABAIXO
# Apague o os.getenv e cole a chave limpa aqui, sem espaços.
MANYCHAT_TOKEN = "COLE_AQUI_O_SEU_TOKEN_DO_MANYCHAT"

headers_supabase = {
    "apikey": KEY_SUPABASE, 
    "Authorization": f"Bearer {KEY_SUPABASE}", 
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

# Voltando para o cabeçalho padrão exigido pelo ManyChat
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
            busca_url = f"https://api.manychat.com/fb/subscriber/findByCustomField?field_name=email&field_value={email}"
            find_res = requests.get(busca_url, headers=headers_manychat)
            
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
        busca_url = f"https://api.manychat.com/fb/subscriber/findByCustomField?field_name=email&field_value={email}"
        find_res = requests.get(busca_url, headers=headers_manychat)
        
        if find_res.status_code == 200:
            subscriber_data = find_res.json().get("data", [])
            if subscriber_data:
                manychat_user_id = subscriber_data[0].get("id")
                
                tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"
                payload_tag = { "subscriber_id": manychat_user_id, "tag_name": "comprou-vigor360" }
                res_tag = requests.post(tag_url, json=payload_tag, headers=headers_manychat)
                
                return {"status": "Sucesso!", "mensagem": f"Tag aplicada no e-mail {email}", "manychat_code": res_tag.status_code}
            return {"status": "Erro", "mensagem": f"E-mail {email} nao encontrado no ManyChat."}
        return {"status": "Erro", "mensagem": "Erro de autenticacao na API do ManyChat.", "status_code": find_res.status_code, "detalhe": find_res.text}
    except Exception as e:
        return {"status": "Erro Critico", "detalhe": str(e)}

@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E BLINDADO"
