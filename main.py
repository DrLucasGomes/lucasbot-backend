from fastapi import FastAPI, Request, BackgroundTasks
import requests
import os
from urllib.parse import urlparse, parse_qs

from kit_utils import (
    metadados_resposta_subscribe,
    primeiro_nome,
)

app = FastAPI()

URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"

KEY = os.getenv("SUPABASE_KEY")
MANYCHAT_TOKEN = os.getenv("MANYCHAT_TOKEN")
CONVERTKIT_API_KEY = os.getenv("CONVERTKIT_API_KEY")
TAG_LEAD_ID = os.getenv("TAG_LEAD_ID")
TAG_ABANDONO_ID = os.getenv("TAG_ABANDONO_ID")
TAG_COMPRADOR_ID = os.getenv("TAG_COMPRADOR_ID")

CAMPOS_PERMITIDOS = {
    "email", "nome", "telefone", "telefone_whatsapp", "telefone_checkout_kiwify",
    "score", "idade", "risco", "status_jornada", "tag", "origem", "campanha",
    "status_testosterona", "tempo_sintoma", "manychat_id", "status_pagamento",
    "produto", "checkout_src", "checkout_utm_source", "checkout_utm_medium",
    "checkout_utm_campaign", "checkout_utm_content", "checkout_utm_term", "origem_compra"
}
CAMPOS_NUMERICOS = {"score", "idade"}
CAMPOS_TELEFONE = {"telefone", "telefone_whatsapp", "telefone_checkout_kiwify"}
STATUS_PAGOS = {"paid", "approved", "order_approved"}
STATUS_ABANDONO = {"abandoned", "cart_abandoned"}


def valor_valido(v):
    if v is None: return False
    texto = str(v).strip()
    if texto == "" or texto.lower() in ["none", "null", "undefined"]: return False
    if texto.startswith("{{") or texto.endswith("}}") or "{{" in texto or "}}" in texto: return False
    return True


def limpar_telefone(telefone):
    if not valor_valido(telefone): return None
    tel = "".join(filter(str.isdigit, str(telefone)))
    return tel if tel else None


def limpar_payload_supabase(dados):
    limpo = {}
    for k, v in dados.items():
        if k not in CAMPOS_PERMITIDOS or not valor_valido(v): continue
        if k in CAMPOS_NUMERICOS:
            try: limpo[k] = int(str(v).strip())
            except Exception: continue
        elif k in CAMPOS_TELEFONE:
            tel = limpar_telefone(v)
            if tel: limpo[k] = tel
        else: limpo[k] = str(v).strip()
    return limpo


def obter_headers_manychat():
    return {"Authorization": f"Bearer {os.getenv('MANYCHAT_TOKEN')}", "Content-Type": "application/json"}


def obter_headers_supabase(prefer=None):
    chave_atual = os.getenv("SUPABASE_KEY")
    headers = {"apikey": chave_atual, "Authorization": f"Bearer {chave_atual}", "Content-Type": "application/json"}
    if prefer: headers["Prefer"] = prefer
    return headers


def resposta_segura(response):
    try: return response.json()
    except Exception: return response.text


def manychat_id_valido(valor):
    return valor_valido(valor) and str(valor).strip().lower() not in ["none", "null", "undefined"]


def buscar_valor_recursivo(objeto, chaves_possiveis):
    chaves_normalizadas = {str(chave).lower() for chave in chaves_possiveis}
    if isinstance(objeto, dict):
        for chave, valor in objeto.items():
            if str(chave).lower() in chaves_normalizadas and valor_valido(valor): return valor
        for valor in objeto.values():
            resultado = buscar_valor_recursivo(valor, chaves_normalizadas)
            if valor_valido(resultado): return resultado
    elif isinstance(objeto, list):
        for item in objeto:
            resultado = buscar_valor_recursivo(item, chaves_normalizadas)
            if valor_valido(resultado): return resultado
    return None


def buscar_parametro_em_urls(objeto, parametro):
    if isinstance(objeto, dict):
        for valor in objeto.values():
            resultado = buscar_parametro_em_urls(valor, parametro)
            if valor_valido(resultado): return resultado
    elif isinstance(objeto, list):
        for item in objeto:
            resultado = buscar_parametro_em_urls(item, parametro)
            if valor_valido(resultado): return resultado
    elif isinstance(objeto, str):
        texto = objeto.strip()
        if "?" in texto and parametro in texto:
            try:
                valores = parse_qs(urlparse(texto).query).get(parametro)
                if valores and valor_valido(valores[0]): return valores[0]
            except Exception: return None
    return None


def extrair_tracking_kiwify(dados_kiwify):
    resultado = {}
    aliases = {"checkout_src": ["src", "sck", "source"], "checkout_utm_source": ["utm_source"],
               "checkout_utm_medium": ["utm_medium"], "checkout_utm_campaign": ["utm_campaign"],
               "checkout_utm_content": ["utm_content"], "checkout_utm_term": ["utm_term"]}
    for campo, chaves in aliases.items():
        valor = buscar_valor_recursivo(dados_kiwify, chaves)
        if not valor_valido(valor): valor = buscar_parametro_em_urls(dados_kiwify, chaves[0])
        resultado[campo] = valor
    return resultado


def extrair_manychat_id_do_src(src):
    if not valor_valido(src): return None
    texto = str(src).strip()
    if texto.startswith("mc_"):
        candidato = texto.replace("mc_", "", 1).strip()
        if manychat_id_valido(candidato): return candidato
    return None


def classificar_origem_compra(src, utm_source, utm_medium=None):
    src_txt = str(src).strip().lower() if valor_valido(src) else ""
    utm_txt = str(utm_source).strip().lower() if valor_valido(utm_source) else ""
    medium_txt = str(utm_medium).strip().lower() if valor_valido(utm_medium) else ""
    if src_txt.startswith("mc_") or utm_txt == "manychat": return "manychat"
    if medium_txt == "qrcode" or src_txt.startswith("qr_"):
        if utm_txt == "youtube" or src_txt.startswith("qr_yt"): return "youtube_qrcode"
        if utm_txt in ["facebook", "meta"] or src_txt.startswith("qr_fb"): return "facebook_qrcode"
        if utm_txt == "instagram" or src_txt.startswith("qr_ig"): return "instagram_qrcode"
        if utm_txt == "pdf" or src_txt.startswith("qr_pdf"): return "pdf_qrcode"
        return "qrcode_outro"
    if "youtube" in src_txt or utm_txt == "youtube": return "youtube_direto"
    if "facebook" in src_txt or utm_txt == "facebook" or "meta" in src_txt or utm_txt == "meta": return "facebook_direto"
    if "instagram" in src_txt or utm_txt == "instagram": return "instagram_direto"
    if "pdf" in src_txt or utm_txt == "pdf": return "pdf_direto"
    if "vsl" in src_txt or "pagina" in src_txt or utm_txt in ["pagina_vendas", "site"]: return "pagina_vendas"
    return "rastreado_outro" if src_txt or utm_txt else "desconhecida"


def status_pagamento_final(status_atual, status_novo):
    atual = str(status_atual).strip().lower() if valor_valido(status_atual) else None
    novo = str(status_novo).strip().lower() if valor_valido(status_novo) else None
    if atual in STATUS_PAGOS and novo in STATUS_ABANDONO: return atual
    return novo


def adicionar_lead_convertkit(email: str, first_name: str = ""):
    if not valor_valido(email): return
    api_secret, tag_lead_id = os.getenv("CONVERTKIT_API_SECRET"), os.getenv("TAG_LEAD_ID")
    if not valor_valido(api_secret) or not valor_valido(tag_lead_id): return
    payload = {"api_secret": api_secret, "email": str(email).strip()}
    first_name = primeiro_nome(first_name)
    if valor_valido(first_name): payload["first_name"] = first_name
    try:
        r = requests.post(f"https://api.convertkit.com/v3/tags/{tag_lead_id}/subscribe", json=payload, timeout=10)
        json_valid, subscriber_id_present, first_name_present = metadados_resposta_subscribe(r)
        print(f"[ConvertKit Lead] operation=subscribe status_http={r.status_code} json_valid={json_valid} subscriber_id_present={subscriber_id_present} first_name_present={first_name_present}")
    except Exception as e: print(f"[ConvertKit Lead] Subscribe falhou: {type(e).__name__}")


def gerenciar_tags_convertkit(email: str, status_pagamento: str):
    """Mantem as tags de recuperacao do Kit coerentes com o estado final da compra."""
    base_url = "https://api.convertkit.com/v3"
    api_secret = os.getenv("CONVERTKIT_API_SECRET")
    tag_abandono_id = os.getenv("TAG_ABANDONO_ID")
    tag_comprador_id = os.getenv("TAG_COMPRADOR_ID")
    if not valor_valido(email) or not valor_valido(api_secret):
        print("[ConvertKit] email ou CONVERTKIT_API_SECRET ausente")
        return
    payload = {"api_secret": api_secret, "email": str(email).strip()}
    status_pagamento = str(status_pagamento).strip().lower()
    try:
        if status_pagamento in STATUS_ABANDONO:
            if not valor_valido(tag_abandono_id):
                print("[ConvertKit] TAG_ABANDONO_ID ausente")
                return
            r = requests.post(f"{base_url}/tags/{tag_abandono_id}/subscribe", json=payload, timeout=10)
            print(f"[ConvertKit] operation=abandoned_subscribe status_http={r.status_code} email={email}")
            return
        if status_pagamento in STATUS_PAGOS:
            if not valor_valido(tag_comprador_id):
                print("[ConvertKit] TAG_COMPRADOR_ID ausente")
                return
            r_add = requests.post(f"{base_url}/tags/{tag_comprador_id}/subscribe", json=payload, timeout=10)
            print(f"[ConvertKit] operation=buyer_subscribe status_http={r_add.status_code} email={email}")
            if valor_valido(tag_abandono_id):
                r_remove = requests.post(f"{base_url}/tags/{tag_abandono_id}/unsubscribe", json=payload, timeout=10)
                print(f"[ConvertKit] operation=abandoned_unsubscribe status_http={r_remove.status_code} email={email}")
    except Exception as e:
        print(f"[ConvertKit] tag_sync_failed error={type(e).__name__} email={email}")


def buscar_lead_por_campo(campo: str, valor: str):
    if not valor_valido(valor): return None
    busca = requests.get(f"{URL}/rest/v1/leads_vigor", params={campo: f"eq.{valor}", "select": "id,email,telefone,telefone_whatsapp,telefone_checkout_kiwify,manychat_id,status_pagamento"}, headers=obter_headers_supabase(), timeout=15)
    if busca.status_code == 200:
        leads = busca.json()
        if isinstance(leads, list) and leads: return leads[0]
    return None


def buscar_lead_existente(manychat_id=None, telefone=None, email=None):
    lead = buscar_lead_por_campo("manychat_id", str(manychat_id).strip()) if manychat_id_valido(manychat_id) else None
    for campo, valor in [("telefone", telefone), ("telefone_whatsapp", telefone), ("telefone_checkout_kiwify", telefone), ("email", email)]:
        if not lead and valor: lead = buscar_lead_por_campo(campo, valor)
    return lead


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        dados_brutos = await request.json(); mc_id = dados_brutos.get("manychat_id")
        if not manychat_id_valido(mc_id): return {"status": "erro", "detalhe": "manychat_id nao encontrado"}
        dados_limpos = limpar_payload_supabase(dados_brutos); dados_limpos["manychat_id"] = str(mc_id).strip()
        response = requests.post(f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id", json=dados_limpos, headers=obter_headers_supabase(prefer="resolution=merge-duplicates,return=representation"), timeout=15)
        sucesso = response.status_code in [200, 201, 204]
        email_lead, first_name = dados_limpos.get("email"), primeiro_nome(dados_limpos.get("nome"))
        if sucesso and valor_valido(email_lead): background_tasks.add_task(adicionar_lead_convertkit, email_lead, first_name or "")
        return {"status": "sucesso" if sucesso else "erro_supabase", "code": response.status_code, "payload_enviado": dados_limpos, "convertkit_lead_agendado": bool(sucesso and valor_valido(email_lead)), "resposta_supabase": resposta_segura(response)}
    except Exception as e: return {"status": "erro_critico", "detalhe": str(e)}


@app.post("/kiwify")
async def webhook_kiwify(request: Request, background_tasks: BackgroundTasks):
    try:
        dados_kiwify = await request.json()
        status = nome = email = telefone = produto = manychat_user_id = None
        tracking = extrair_tracking_kiwify(dados_kiwify)
        checkout_src, checkout_utm_source, checkout_utm_medium = tracking.get("checkout_src"), tracking.get("checkout_utm_source"), tracking.get("checkout_utm_medium")
        origem_compra = classificar_origem_compra(checkout_src, checkout_utm_source, checkout_utm_medium)
        ordem = dados_kiwify.get("order") or dados_kiwify.get("Order"); carrinho = dados_kiwify.get("cart") or dados_kiwify.get("Cart")
        if ordem:
            status = ordem.get("order_status"); bloco_produto = ordem.get("Product") or ordem.get("product") or {}; produto = bloco_produto.get("product_name")
            bloco_customer = ordem.get("Customer") or ordem.get("customer") or {}; nome = bloco_customer.get("full_name") or bloco_customer.get("name"); email = bloco_customer.get("email"); telefone = bloco_customer.get("mobile") or bloco_customer.get("phone")
            custom_variables = ordem.get("custom_variables") or ordem.get("CustomVariables") or {}; manychat_user_id = custom_variables.get("manychat_id") if isinstance(custom_variables, dict) else None
        elif carrinho:
            status = carrinho.get("status"); produto = carrinho.get("product_name"); nome = carrinho.get("name") or carrinho.get("full_name"); email = carrinho.get("email"); telefone = carrinho.get("phone") or carrinho.get("mobile")
            custom_variables = carrinho.get("custom_variables") or carrinho.get("CustomVariables") or {}; manychat_user_id = custom_variables.get("manychat_id") if isinstance(custom_variables, dict) else None
        manychat_id_do_src = extrair_manychat_id_do_src(checkout_src)
        if not manychat_id_valido(manychat_user_id) and manychat_id_valido(manychat_id_do_src): manychat_user_id = manychat_id_do_src
        email = email or dados_kiwify.get("email"); nome = nome or dados_kiwify.get("name") or dados_kiwify.get("nome"); telefone = telefone or dados_kiwify.get("phone") or dados_kiwify.get("mobile"); telefone = limpar_telefone(telefone)
        if not email:
            fonte_debug = dados_kiwify.get("data") if isinstance(dados_kiwify.get("data"), dict) else dados_kiwify; ordem_debug = fonte_debug.get("order") or fonte_debug.get("Order") or fonte_debug
            if not isinstance(ordem_debug, dict): ordem_debug = {}
            customer_debug = ordem_debug.get("Customer") or ordem_debug.get("customer") or fonte_debug.get("Customer") or fonte_debug.get("customer") or {}; customer_debug = customer_debug if isinstance(customer_debug, dict) else {}
            product_debug = ordem_debug.get("Product") or ordem_debug.get("product") or fonte_debug.get("Product") or fonte_debug.get("product") or {}; product_debug = product_debug if isinstance(product_debug, dict) else {}
            email = customer_debug.get("email") or customer_debug.get("Email") or fonte_debug.get("email") or fonte_debug.get("Email")
            nome = nome or customer_debug.get("full_name") or customer_debug.get("name") or customer_debug.get("first_name") or fonte_debug.get("full_name") or fonte_debug.get("name") or fonte_debug.get("nome")
            telefone = telefone or customer_debug.get("mobile") or customer_debug.get("phone") or fonte_debug.get("mobile") or fonte_debug.get("phone")
            status = status or ordem_debug.get("order_status") or ordem_debug.get("webhook_event_type") or ordem_debug.get("status")
            produto = produto or product_debug.get("product_name") or product_debug.get("product_offer_name") or product_debug.get("name"); telefone = limpar_telefone(telefone)
        if not email: return {"status": "ignorado", "detalhe": "JSON sem dados de contato acessiveis", "chaves_recebidas": list(dados_kiwify.keys()), "tracking_detectado": tracking, "origem_compra": origem_compra, "payload_recebido": dados_kiwify}
        if status: status = str(status).strip().lower()
        lead_existente = None
        if status in STATUS_ABANDONO:
            try: lead_existente = buscar_lead_existente(manychat_id=manychat_user_id, telefone=telefone, email=email)
            except Exception as e: print(f"[Kiwify] Falha ao consultar estado atual antes do abandono: {str(e)}")
            if lead_existente: status = status_pagamento_final(lead_existente.get("status_pagamento"), status)
        payload_supabase = limpar_payload_supabase({"nome": nome, "email": email, "telefone": telefone, "telefone_checkout_kiwify": telefone, "status_pagamento": status, "produto": produto, **tracking, "origem_compra": origem_compra})
        headers_supabase_padrao = obter_headers_supabase(prefer="return=representation"); headers_supabase_upsert = obter_headers_supabase(prefer="resolution=merge-duplicates,return=representation")
        supabase_acao = supabase_code = supabase_resposta = manychat_id_para_tag = None
        if manychat_id_valido(manychat_user_id):
            manychat_user_id = str(manychat_user_id).strip(); manychat_id_para_tag = manychat_user_id; payload_supabase["manychat_id"] = manychat_user_id
            response_supabase = requests.post(f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id", json=payload_supabase, headers=headers_supabase_upsert, timeout=15)
            supabase_acao, supabase_code, supabase_resposta = "upsert_por_manychat_id", response_supabase.status_code, resposta_segura(response_supabase)
        else:
            if not lead_existente: lead_existente = buscar_lead_existente(telefone=telefone, email=email)
            if lead_existente:
                lead_id, id_existente = lead_existente.get("id"), lead_existente.get("manychat_id")
                if manychat_id_valido(id_existente): manychat_id_para_tag = str(id_existente).strip()
                response_patch = requests.patch(f"{URL}/rest/v1/leads_vigor", params={"id": f"eq.{lead_id}"}, json=payload_supabase, headers=headers_supabase_padrao, timeout=15)
                supabase_acao, supabase_code, supabase_resposta = "patch_por_telefone_whatsapp_checkout_ou_email", response_patch.status_code, resposta_segura(response_patch)
            else:
                response_insert = requests.post(f"{URL}/rest/v1/leads_vigor", json=payload_supabase, headers=headers_supabase_padrao, timeout=15)
                supabase_acao, supabase_code, supabase_resposta = "insert_novo_lead", response_insert.status_code, resposta_segura(response_insert)
        if email and status: background_tasks.add_task(gerenciar_tags_convertkit, email, status)
        if status in STATUS_PAGOS:
            headers_mc = obter_headers_manychat()
            if manychat_id_valido(manychat_id_para_tag):
                try:
                    res_tag = requests.post("https://api.manychat.com/fb/subscriber/addTagByName", json={"subscriber_id": int(str(manychat_id_para_tag).strip()), "tag_name": "comprou-vigor360"}, headers=headers_mc, timeout=15)
                    return {"status": "sucesso_id_direto", "status_pagamento": status, "email": email, "telefone": telefone, "manychat_id_usado": manychat_id_para_tag, "tracking_detectado": tracking, "origem_compra": origem_compra, "supabase_acao": supabase_acao, "supabase_code": supabase_code, "supabase_resposta": supabase_resposta, "manychat_code": res_tag.status_code, "manychat_resposta": resposta_segura(res_tag)}
                except Exception as e: print(f"[ManyChat] Falha tag ID direto: {str(e)}")
            subscriber_data = []; find_res = None
            if os.getenv("MANYCHAT_TOKEN"):
                find_res = requests.post("https://api.manychat.com/fb/subscriber/findByCustomField", json={"field_name": "email", "field_value": email}, headers=headers_mc, timeout=15)
                try: subscriber_data = find_res.json().get("data", [])
                except Exception: subscriber_data = []
                if not subscriber_data and telefone:
                    find_res = requests.get("https://api.manychat.com/fb/subscriber/findByName", params={"name": telefone}, headers=headers_mc, timeout=15)
                    try:
                        dados_find = find_res.json(); subscriber_data = dados_find.get("data", []) if isinstance(dados_find, dict) and "data" in dados_find else ([dados_find] if isinstance(dados_find, dict) else [])
                    except Exception: subscriber_data = []
                if subscriber_data and isinstance(subscriber_data, list):
                    uid = subscriber_data[0].get("id")
                    if uid:
                        res_tag = requests.post("https://api.manychat.com/fb/subscriber/addTagByName", json={"subscriber_id": int(uid), "tag_name": "comprou-vigor360"}, headers=headers_mc, timeout=15)
                        return {"status": "sucesso_funil_busca", "status_pagamento": status, "email": email, "telefone": telefone, "manychat_id_encontrado": uid, "tracking_detectado": tracking, "origem_compra": origem_compra, "supabase_acao": supabase_acao, "supabase_code": supabase_code, "supabase_resposta": supabase_resposta, "manychat_code": res_tag.status_code, "manychat_resposta": resposta_segura(res_tag)}
            return {"status": "comprador_salvo_mas_nao_encontrado_no_manychat", "status_pagamento": status, "email": email, "telefone": telefone, "tracking_detectado": tracking, "origem_compra": origem_compra, "supabase_acao": supabase_acao, "supabase_code": supabase_code, "supabase_resposta": supabase_resposta, "manychat_find_code": find_res.status_code if find_res else None, "manychat_find_resposta": resposta_segura(find_res) if find_res else None}
        return {"status": "processado", "status_pagamento": status, "email": email, "telefone": telefone, "supabase_acao": supabase_acao, "supabase_code": supabase_code, "supabase_resposta": supabase_resposta}
    except Exception as e: return {"status": "erro_critico", "detalhe": str(e)}


@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE COM RASTREAMENTO DE COMPRA"
