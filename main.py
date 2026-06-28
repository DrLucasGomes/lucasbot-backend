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

headers_supabase_padrao = {
    "apikey": KEY, 
    "Authorization": f"Bearer {KEY}", 
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

        dados_limpos = {}
        for k, v in dados_brutos.items():
            if v is not None and str(v).strip() != "" and str(v).lower() != "none":
                dados_limpos[k] = v

        dados_limpos["manychat_id"] = mc_id_str

        headers_supabase = {
            "apikey": KEY, 
            "Authorization": f"Bearer {KEY}", 
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        }
        
        url_upsert = f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id"
        response = requests.post(url_upsert, json=dados_limpos, headers=headers_supabase)
        
        return {"status": "sucesso", "code": response.status_code}
    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

# ROTA DA KIWIFY CORRIGIDA E ADAPTADA AOS JSONS REAIS
@app.post("/kiwify")
async def webhook_kiwify(request: Request):
    try:
        dados_kiwify = await request.json()
        
        # Inicializa variáveis padrão
        status = None
        nome = None
        email = None
        telefone = None
        produto = None
        manychat_user_id = None

        # 1. TRATAMENTO PARA COMPRA (CONFORME SEU PRIMEIRO JSON)
        if "order" in dados_kiwify:
            ordem = dados_kiwify.get("order", {})
            status = ordem.get("order_status")  # vai receber "paid"
            produto = ordem.get("Product", {}).get("product_name")
            
            customer = ordem.get("Customer", {})
            nome = customer.get("full_name")
            email = customer.get("email")
            telefone = customer.get("mobile", "")
            
            # Busca o id nas custom_variables se existirem
            custom_variables = ordem.get("custom_variables", {})
            if custom_variables:
                manychat_user_id = custom_variables.get("manychat_id")

        # 2. TRATAMENTO PARA CARRINHO ABANDONADO (CONFORME SEU SEGUNDO JSON)
        elif "cart" in dados_kiwify:
            carrinho = dados_kiwify.get("cart", {})
            status = carrinho.get("status")  # vai receber "abandoned"
            produto = carrinho.get("product_name")
            nome = carrinho.get("name")
            email = carrinho.get("email")
            telefone = carrinho.get("phone", "")

        # Limpa o telefone deixando só números
        if telefone:
            telefone = "".join(filter(str.isdigit, str(telefone)))

        # Se não capturou dados mínimos, aborta para não quebrar o banco
        if not email:
            return {"status": "ignorado", "detalhe": "JSON sem dados de cliente"}

        # Prepara a gravação no Supabase
        payload_supabase = {
            "nome": nome,
            "email": email,
            "telefone": telefone,
            "status_pagamento": status,
            "produto": produto
        }

        try:
            if manychat_user_id and str(manychat_user_id).strip() != "" and str(manychat_user_id).lower() != "none":
                payload_supabase["manychat_id"] = str(manychat_user_id).strip()
                headers_upsert = {
                    "apikey": KEY, 
                    "Authorization": f"Bearer {KEY}", 
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates"
                }
                requests.post(f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id", json=payload_supabase, headers=headers_upsert)
            else:
                # Se não veio ID, joga como registro avulso para não sobrescrever a jornada do Whats
                requests.post(f"{URL}/rest/v1/leads_vigor", json=payload_supabase, headers=headers_supabase_padrao)
        except Exception as err_banco:
            print(f"Erro banco kiwify: {str(err_banco)}")

        # 3. DISPARO DE TAG DE COMPRA NO MANYCHAT (Se status for "paid" ou "approved")
        if status in ["paid", "approved", "order_approved"]:
            if manychat_user_id:
                tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"
                payload_tag = {"subscriber_id": int(manychat_user_id), "tag_name": "comprou-vigor360"}
                res_tag = requests.post(tag_url, json=payload_tag, headers=headers_manychat)
                return {"status": "sucesso_id_direto", "manychat_code": res_tag.status_code}

            # Busca detetive por email se o ID direto falhar
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
            
            return {"status": "comprador_salvo_mas_nao_encontrado_no_manychat"}
            
        return {"status": "processado_status", "status": status}
    except Exception as e:
        return {"status": "erro_critico", "detalhe": str(e)}

@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E BLINDADO"
