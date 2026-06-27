from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

URL_SUPABASE = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY_SUPABASE = os.getenv("SUPABASE_KEY") 
MANYCHAT_TOKEN = os.getenv("MANYCHAT_TOKEN")

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
        
        # Pega as variáveis customizadas enviadas no link da Kiwify
        custom_variables = dados_kiwify.get("custom_variables", {})
        manychat_user_id = custom_variables.get("manychat_id") # O ID vem aqui agora!
        
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

        # Se a compra foi aprovada E nós temos o ID do ManyChat vindo da Kiwify
        if status == "approved" and manychat_user_id:
            tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"
            payload_tag = {
                "subscriber_id": int(manychat_user_id),
                "tag_name": "comprou-vigor360"
            }
            res_tag = requests.post(tag_url, json=payload_tag, headers=headers_manychat)
            print(f"MANYCHAT TAG STATUS: {res_tag.status_code}")
            return {"status": "sucesso_funil", "manychat_code": res_tag.status_code}
            
        return {"status": "processado_sem_tag", "status": status, "has_id": bool(manychat_user_id)}
    except Exception as e:
        print(f"Erro Geral: {str(e)}")
        return {"status": "erro_critico", "detalhe": str(e)}

# ROTA DE TESTE DIRETO PELO ID
@app.get("/testar-id")
def testar_id(id_user: int):
    try:
        tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"
        payload_tag = { "subscriber_id": id_user, "tag_name": "comprou-vigor360" }
        res_tag = requests.post(tag_url, json=payload_tag, headers=headers_manychat)
        return {"status": "Resposta da API", "manychat_code": res_tag.status_code, "detalhe": res_tag.text}
    except Exception as e:
        return {"status": "Erro", "detalhe": str(e)}

@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E BLINDADO"
