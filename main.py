from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY = os.getenv("SUPABASE_KEY") 

# TOKEN DA API PÚBLICA DO MANYCHAT
MANYCHAT_TOKEN = "COLE_AQUI_O_SEU_TOKEN_REAL"

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

@app.post("/kiwify")
async def webhook_kiwify(request: Request):
    try:
        dados_kiwify = await request.json()
        
        status = None
        nome = None
        email = None
        telefone = None
        produto = None
        manychat_user_id = None

        # 1. PEGA O BLOCO DA ORDEM (COMPRA) TRATANDO MAIÚSCULAS/MINÚSCULAS
        ordem = dados_kiwify.get("order") or dados_kiwify.get("Order")
        carrinho = dados_kiwify.get("cart") or dados_kiwify.get("Cart")

        if ordem:
            status = ordem.get("order_status")  # "paid"
            
            # Extrai dados do Produto tratando "Product" ou "product"
            bloco_produto = ordem.get("Product") or ordem.get("product") or {}
            produto = bloco_produto.get("product_name")
            
            # Extrai dados do Cliente tratando "Customer" ou "customer"
            bloco_customer = ordem.get("Customer") or ordem.get("customer") or {}
            nome = bloco_customer.get("full_name") or bloco_customer.get("name")
            email = bloco_customer.get("email")
            telefone = bloco_customer.get("mobile") or bloco_customer.get("phone")
            
            # Busca variáveis customizadas de rastreio
            custom_variables = ordem.get("custom_variables") or ordem.get("CustomVariables") or {}
            if custom_variables:
                manychat_user_id = custom_variables.get("manychat_id")

        # 2. PEGA O BLOCO DO CARRINHO ABANDONADO
        elif carrinho:
            status = carrinho.get("status")  # "abandoned"
            produto = carrinho.get("product_name")
            nome = carrinho.get("name") or carrinho.get("full_name")
            email = carrinho.get("email")
            telefone = carrinho.get("phone") or carrinho.get("mobile")

        # Limpa o telefone deixando apenas números
        if telefone:
            telefone = "".join(filter(str.isdigit, str(telefone)))

        # Se a checagem falhar por completo, usa segurança máxima buscando na raiz do payload
        if not email:
            email = dados_kiwify.get("email")
            nome = dados_kiwify.get("name")
            telefone = dados_kiwify.get("phone")

        if not email:
            return {"status": "ignorado", "detalhe": "JSON sem dados de contato acessiveis"}

        payload_supabase = {
            "nome": nome,
            "email": email,
            "telefone": telefone,
            "status_pagamento": status,
            "produto": produto
        }

        # 3. UNIFICAÇÃO NA MESMA LINHA DO SUPABASE
        lead_encontrado_por_telefone = False
        
        if manychat_user_id and str(manychat_user_id).strip() != "" and str(manychat_user_id).lower() != "none":
            payload_supabase["manychat_id"] = str(manychat_user_id).strip()
            headers_upsert = {
                "apikey": KEY, 
                "Authorization": f"Bearer {KEY}", 
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates"
            }
            requests.post(f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id", json=payload_supabase, headers=headers_upsert)
        
        elif telefone:
            url_busca = f"{URL}/rest/v1/leads_vigor?telefone=eq.{telefone}"
            resposta_busca = requests.get(url_busca, headers=headers_supabase_padrao)
            
            if resposta_busca.status_code == 200:
                leads = resposta_busca.json()
                if isinstance(leads, list) and len(leads) > 0:
                    id_existente = leads[0].get("manychat_id")
                    if id_existente:
                        url_patch = f"{URL}/rest/v1/leads_vigor?manychat_id=eq.{id_existente}"
                        payload_patch = {
                            "status_pagamento": status,
                            "produto": produto,
                            "email": email
                        }
                        requests.patch(url_patch, json=payload_patch, headers=headers_supabase_padrao)
                        lead_encontrado_por_telefone = True

        if not manychat_user_id and not lead_encontrado_por_telefone:
            requests.post(f"{URL}/rest/v1/leads_vigor", json=payload_supabase, headers=headers_supabase_padrao)

        # 4. ENTREGA DE TAGS NO MANYCHAT PARA PEDIDOS PAGOS
        if status in ["paid", "approved", "order_approved"]:
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
            
            return {"status": "comprador_salvo_mas_nao_encontrado_no_manychat"}
            
        return {"status": "processado_status", "status": status}
    except Exception as e:
        return {"status": "erro_critico", "detalhe": str(e)}

@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E BLINDADO"
