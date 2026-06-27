from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

URL_SUPABASE = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY_SUPABASE = os.getenv("SUPABASE_KEY") 

# TOKEN DA API PÚBLICA DO MANYCHAT
MANYCHAT_TOKEN = "3921505:a4bbd6f7301c5fd1cc27d876f762d0bf"

headers_supabase = {
    "apikey": KEY_SUPABASE, 
    "Authorization": f"Bearer {KEY_SUPABASE}", 
    "Content-Type": "application/json"
}

headers_manychat = {
    "Authorization": f"Bearer {MANYCHAT_TOKEN}",
    "Content-Type": "application/json"
}

@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados_novos = await request.json()
        mc_id = dados_novos.get("manychat_id")
        
        if not mc_id:
            return {"status": "erro", "detalhe": "manychat_id nao enviado"}
            
        mc_id_str = str(mc_id).strip()

        # 1. BUSCA SE O LEAD JÁ EXISTE NO BANCO VIA GET
        url_busca = f"{URL_SUPABASE}/rest/v1/leads_vigor?manychat_id=eq.{mc_id_str}"
        res_busca = requests.get(url_busca, headers=headers_supabase)
        leads = res_busca.json()

        if isinstance(leads, list) and len(leads) > 0:
            # LEAD JÁ EXISTE: Vamos mesclar os dados antigos com os novos no Python
            lead_antigo = leads[0]
            
            # Cria um payload contendo os dados antigos, mas sobrescreve com os novos que NÃO forem vazios
            payload_atualizacao = {}
            for chave, valor in lead_antigo.items():
                # Mantém o que já tinha se o ManyChat não enviou nada novo nesta etapa
                payload_atualizacao[chave] = valor
            
            for chave, valor in dados_novos.items():
                if valor is not None and valor != "":
                    payload_atualizacao[chave] = valor

            # Remove chaves de sistema do Supabase para não dar erro na escrita
            payload_atualizacao.pop("id", None)
            payload_atualizacao.pop("created_at", None)

            # Faz o UPDATE real via PATCH na linha específica
            res_update = requests.patch(url_busca, json=payload_atualizacao, headers=headers_supabase)
            return {"status": "atualizado", "code": res_update.status_code}
            
        else:
            # LEAD NÃO EXISTE: Criação limpa da primeira linha
            res_insercao = requests.post(f"{URL_SUPABASE}/rest/v1/leads_vigor", json=dados_novos, headers=headers_supabase)
            return {"status": "criado", "code": res_insercao.status_code}

    except Exception as e:
        return {"status": "erro", "detalhe": str(e)}

# ROTA DA KIWIFY
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
            payload_supabase = {
                "nome": customer.get("name"),
                "email": email,
                "telefone": telefone,
                "status_pagamento": status,
                "produto": dados_kiwify.get("product_name")
            }
            requests.post(f"{URL_SUPABASE}/rest/v1/leads_vigor", json=payload_supabase, headers=headers_supabase)
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

@app.get("/testar-id")
def testar_id(id_user: int):
    try:
        tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"
        payload_tag = { "subscriber_id": id_user, "tag_name": "comprou-vigor360" }
        res_tag = requests.post(tag_url, json=payload_tag, headers=headers_manychat)
        return {"status": "Comando Enviado!", "manychat_code": res_tag.status_code}
    except Exception as e:
        return {"status": "Erro", "detalhe": str(e)}

@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E BLINDADO"
