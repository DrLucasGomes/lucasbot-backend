from fastapi import FastAPI, Request, BackgroundTasks
import requests
import os
from urllib.parse import urlparse, parse_qs

from kit_utils import primeiro_nome

app = FastAPI()

URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"

KEY = os.getenv("SUPABASE_KEY")
MANYCHAT_TOKEN = os.getenv("MANYCHAT_TOKEN")
CONVERTKIT_API_KEY = os.getenv("CONVERTKIT_API_KEY")
TAG_LEAD_ID = os.getenv("TAG_LEAD_ID")
TAG_ABANDONO_ID = os.getenv("TAG_ABANDONO_ID")
TAG_COMPRADOR_ID = os.getenv("TAG_COMPRADOR_ID")

CAMPOS_PERMITIDOS = {
    "email",
    "nome",
    "telefone",
    "telefone_whatsapp",
    "telefone_checkout_kiwify",
    "score",
    "idade",
    "risco",
    "status_jornada",
    "tag",
    "origem",
    "campanha",
    "status_testosterona",
    "tempo_sintoma",
    "manychat_id",
    "status_pagamento",
    "produto",
    "checkout_src",
    "checkout_utm_source",
    "checkout_utm_medium",
    "checkout_utm_campaign",
    "checkout_utm_content",
    "checkout_utm_term",
    "origem_compra"
}

CAMPOS_NUMERICOS = {"score", "idade"}

CAMPOS_TELEFONE = {
    "telefone",
    "telefone_whatsapp",
    "telefone_checkout_kiwify"
}

STATUS_PAGOS = {"paid", "approved", "order_approved"}
STATUS_ABANDONO = {"abandoned", "cart_abandoned"}


def valor_valido(v):
    if v is None:
        return False

    texto = str(v).strip()

    if texto == "":
        return False

    if texto.lower() in ["none", "null", "undefined"]:
        return False

    # Evita gravar placeholders quebrados do ManyChat, como {{cuf_14421642}}
    if texto.startswith("{{") or texto.endswith("}}") or "{{" in texto or "}}" in texto:
        return False

    return True


def limpar_telefone(telefone):
    if not valor_valido(telefone):
        return None

    tel = "".join(filter(str.isdigit, str(telefone)))

    return tel if tel else None


def limpar_payload_supabase(dados):
    limpo = {}

    for k, v in dados.items():
        if k not in CAMPOS_PERMITIDOS:
            continue

        if not valor_valido(v):
            continue

        if k in CAMPOS_NUMERICOS:
            try:
                limpo[k] = int(str(v).strip())
            except Exception:
                continue

        elif k in CAMPOS_TELEFONE:
            tel = limpar_telefone(v)
            if tel:
                limpo[k] = tel

        else:
            limpo[k] = str(v).strip()

    return limpo


def obter_headers_manychat():
    return {
        "Authorization": f"Bearer {os.getenv('MANYCHAT_TOKEN')}",
        "Content-Type": "application/json"
    }


def obter_headers_supabase(prefer=None):
    chave_atual = os.getenv("SUPABASE_KEY")

    headers = {
        "apikey": chave_atual,
        "Authorization": f"Bearer {chave_atual}",
        "Content-Type": "application/json"
    }

    if prefer:
        headers["Prefer"] = prefer

    return headers


def resposta_segura(response):
    try:
        return response.json()
    except Exception:
        return response.text


def manychat_id_valido(valor):
    if not valor_valido(valor):
        return False

    return str(valor).strip().lower() not in ["none", "null", "undefined"]


def buscar_valor_recursivo(objeto, chaves_possiveis):
    """
    Procura uma chave em qualquer nível do JSON.
    Isso deixa o parser resistente, porque a Kiwify pode mandar src/UTM em blocos diferentes.
    """
    chaves_normalizadas = {str(chave).lower() for chave in chaves_possiveis}

    if isinstance(objeto, dict):
        for chave, valor in objeto.items():
            if str(chave).lower() in chaves_normalizadas and valor_valido(valor):
                return valor

        for valor in objeto.values():
            resultado = buscar_valor_recursivo(valor, chaves_normalizadas)
            if valor_valido(resultado):
                return resultado

    elif isinstance(objeto, list):
        for item in objeto:
            resultado = buscar_valor_recursivo(item, chaves_normalizadas)
            if valor_valido(resultado):
                return resultado

    return None


def buscar_parametro_em_urls(objeto, parametro):
    """
    Procura uma URL dentro do JSON e tenta extrair parâmetro de query string.
    Exemplo: payment_url contendo ?src=facebook_direto&utm_source=facebook
    """
    if isinstance(objeto, dict):
        for valor in objeto.values():
            resultado = buscar_parametro_em_urls(valor, parametro)
            if valor_valido(resultado):
                return resultado

    elif isinstance(objeto, list):
        for item in objeto:
            resultado = buscar_parametro_em_urls(item, parametro)
            if valor_valido(resultado):
                return resultado

    elif isinstance(objeto, str):
        texto = objeto.strip()

        if "?" in texto and parametro in texto:
            try:
                parsed = urlparse(texto)
                query = parse_qs(parsed.query)
                valores = query.get(parametro)
                if valores and valor_valido(valores[0]):
                    return valores[0]
            except Exception:
                return None

    return None


def extrair_tracking_kiwify(dados_kiwify):
    """
    Extrai src e UTMs do webhook da Kiwify.
    Primeiro tenta por chave direta/recursiva; depois tenta achar dentro de URLs do payload.
    """
    src = buscar_valor_recursivo(dados_kiwify, ["src", "sck", "source"])
    utm_source = buscar_valor_recursivo(dados_kiwify, ["utm_source"])
    utm_medium = buscar_valor_recursivo(dados_kiwify, ["utm_medium"])
    utm_campaign = buscar_valor_recursivo(dados_kiwify, ["utm_campaign"])
    utm_content = buscar_valor_recursivo(dados_kiwify, ["utm_content"])
    utm_term = buscar_valor_recursivo(dados_kiwify, ["utm_term"])

    if not valor_valido(src):
        src = buscar_parametro_em_urls(dados_kiwify, "src")
    if not valor_valido(utm_source):
        utm_source = buscar_parametro_em_urls(dados_kiwify, "utm_source")
    if not valor_valido(utm_medium):
        utm_medium = buscar_parametro_em_urls(dados_kiwify, "utm_medium")
    if not valor_valido(utm_campaign):
        utm_campaign = buscar_parametro_em_urls(dados_kiwify, "utm_campaign")
    if not valor_valido(utm_content):
        utm_content = buscar_parametro_em_urls(dados_kiwify, "utm_content")
    if not valor_valido(utm_term):
        utm_term = buscar_parametro_em_urls(dados_kiwify, "utm_term")

    return {
        "checkout_src": src,
        "checkout_utm_source": utm_source,
        "checkout_utm_medium": utm_medium,
        "checkout_utm_campaign": utm_campaign,
        "checkout_utm_content": utm_content,
        "checkout_utm_term": utm_term
    }


def extrair_manychat_id_do_src(src):
    if not valor_valido(src):
        return None

    texto = str(src).strip()

    if texto.startswith("mc_"):
        candidato = texto.replace("mc_", "", 1).strip()
        if manychat_id_valido(candidato):
            return candidato

    return None


def classificar_origem_compra(src, utm_source):
    src_txt = str(src).strip().lower() if valor_valido(src) else ""
    utm_txt = str(utm_source).strip().lower() if valor_valido(utm_source) else ""

    if src_txt.startswith("mc_") or utm_txt == "manychat":
        return "manychat"
    if "youtube" in src_txt or utm_txt == "youtube":
        return "youtube_direto"
    if "facebook" in src_txt or utm_txt == "facebook" or "meta" in src_txt or utm_txt == "meta":
        return "facebook_direto"
    if "instagram" in src_txt or utm_txt == "instagram":
        return "instagram_direto"
    if "vsl" in src_txt or "pagina" in src_txt or utm_txt in ["pagina_vendas", "site"]:
        return "pagina_vendas"
    if src_txt or utm_txt:
        return "rastreado_outro"

    return "desconhecida"


def status_pagamento_final(status_atual, status_novo):
    atual = str(status_atual).strip().lower() if valor_valido(status_atual) else None
    novo = str(status_novo).strip().lower() if valor_valido(status_novo) else None

    # Regra critica: pagamento confirmado e terminal. Um evento atrasado de
    # abandono nunca pode rebaixar um comprador para abandonado.
    if atual in STATUS_PAGOS and novo in STATUS_ABANDONO:
        return atual

    return novo


def adicionar_lead_convertkit(email: str, first_name: str = ""):
    """
    Adiciona lead comum vindo do ManyChat na tag TAG_LEAD_ID do ConvertKit/Kit.
    Esta função é chamada pelo /webhook quando o ManyChat envia um email.
    """
    if not valor_valido(email):
        print("[ConvertKit Lead] Email invalido ou vazio")
        return

    api_key = os.getenv("CONVERTKIT_API_KEY")
    tag_lead_id = os.getenv("TAG_LEAD_ID")

    if not valor_valido(api_key):
        print("[ConvertKit Lead] CONVERTKIT_API_KEY ausente")
        return

    if not valor_valido(tag_lead_id):
        print("[ConvertKit Lead] TAG_LEAD_ID ausente")
        return

    url = f"https://api.convertkit.com/v3/tags/{tag_lead_id}/subscribe"

    payload = {
        "api_key": api_key,
        "email": str(email).strip()
    }
    first_name = primeiro_nome(first_name)
    if first_name:
        payload["first_name"] = first_name

    try:
        r = requests.post(url, json=payload, timeout=10)
        print(f"[ConvertKit Lead] Subscribe HTTP {r.status_code}")
    except Exception as e:
        print(f"[ConvertKit Lead] Subscribe falhou: {type(e).__name__}")

def gerenciar_tags_convertkit(email: str, status_pagamento: str):
    base_url = "https://api.convertkit.com/v3"
    payload = {
        "api_key": os.getenv("CONVERTKIT_API_KEY"),
        "email": email
    }

    status_pagamento = str(status_pagamento).strip().lower()

    is_abandoned = status_pagamento in ["abandoned", "cart_abandoned"]
    is_approved = status_pagamento in ["paid", "approved", "order_approved"]

    if is_abandoned:
        url = f"{base_url}/tags/{os.getenv('TAG_ABANDONO_ID')}/subscribe"

        try:
            r = requests.post(url, json=payload, timeout=10)
            print(f"[ConvertKit] Abandono aplicado: {email} | {r.status_code} | {r.text}")
        except Exception as e:
            print(f"[ConvertKit Erro] Falha ao aplicar abandono: {str(e)}")

    elif is_approved:
        url_add = f"{base_url}/tags/{os.getenv('TAG_COMPRADOR_ID')}/subscribe"
        url_remove = f"{base_url}/tags/{os.getenv('TAG_ABANDONO_ID')}/unsubscribe"

        try:
            r1 = requests.post(url_add, json=payload, timeout=10)
            print(f"[ConvertKit] Comprador aplicado: {email} | {r1.status_code} | {r1.text}")

            if os.getenv("TAG_ABANDONO_ID"):
                r2 = requests.post(url_remove, json=payload, timeout=10)
                print(f"[ConvertKit] Abandono removido: {email} | {r2.status_code} | {r2.text}")

        except Exception as e:
            print(f"[ConvertKit Erro] Falha ao atualizar comprador: {str(e)}")


def buscar_lead_por_campo(campo: str, valor: str):
    if not valor_valido(valor):
        return None

    busca = requests.get(
        f"{URL}/rest/v1/leads_vigor",
        params={
            campo: f"eq.{valor}",
            "select": "id,email,telefone,telefone_whatsapp,telefone_checkout_kiwify,manychat_id,status_pagamento"
        },
        headers=obter_headers_supabase(),
        timeout=15
    )

    if busca.status_code == 200:
        leads = busca.json()
        if isinstance(leads, list) and len(leads) > 0:
            return leads[0]

    return None


def buscar_lead_existente(manychat_id=None, telefone=None, email=None):
    lead = None

    if manychat_id_valido(manychat_id):
        lead = buscar_lead_por_campo("manychat_id", str(manychat_id).strip())

    if not lead and telefone:
        lead = buscar_lead_por_campo("telefone", telefone)

    if not lead and telefone:
        lead = buscar_lead_por_campo("telefone_whatsapp", telefone)

    if not lead and telefone:
        lead = buscar_lead_por_campo("telefone_checkout_kiwify", telefone)

    if not lead and email:
        lead = buscar_lead_por_campo("email", email)

    return lead


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        dados_brutos = await request.json()

        mc_id = dados_brutos.get("manychat_id")

        if not manychat_id_valido(mc_id):
            return {
                "status": "erro",
                "detalhe": "manychat_id nao encontrado"
            }

        dados_limpos = limpar_payload_supabase(dados_brutos)
        dados_limpos["manychat_id"] = str(mc_id).strip()

        headers_supabase = obter_headers_supabase(
            prefer="resolution=merge-duplicates,return=representation"
        )

        url_upsert = f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id"

        response = requests.post(
            url_upsert,
            json=dados_limpos,
            headers=headers_supabase,
            timeout=15
        )

        sucesso = response.status_code in [200, 201, 204]

        email_lead = dados_limpos.get("email")
        first_name = primeiro_nome(dados_limpos.get("nome"))

        # Novo: se o ManyChat mandou email, adiciona o lead na tag TAG_LEAD_ID do ConvertKit.
        # Roda em background para não atrasar nem quebrar a resposta do ManyChat.
        if sucesso and valor_valido(email_lead):
            if first_name:
                background_tasks.add_task(
                    adicionar_lead_convertkit, email_lead, first_name
                )
            else:
                background_tasks.add_task(adicionar_lead_convertkit, email_lead)

        return {
            "status": "sucesso" if sucesso else "erro_supabase",
            "code": response.status_code,
            "payload_enviado": dados_limpos,
            "convertkit_lead_agendado": bool(sucesso and valor_valido(email_lead)),
            "resposta_supabase": resposta_segura(response)
        }

    except Exception as e:
        return {
            "status": "erro_critico",
            "detalhe": str(e)
        }


@app.post("/kiwify")
async def webhook_kiwify(request: Request, background_tasks: BackgroundTasks):
    try:
        dados_kiwify = await request.json()

        status = None
        nome = None
        email = None
        telefone = None
        produto = None
        manychat_user_id = None

        tracking = extrair_tracking_kiwify(dados_kiwify)
        checkout_src = tracking.get("checkout_src")
        checkout_utm_source = tracking.get("checkout_utm_source")
        origem_compra = classificar_origem_compra(checkout_src, checkout_utm_source)

        ordem = dados_kiwify.get("order") or dados_kiwify.get("Order")
        carrinho = dados_kiwify.get("cart") or dados_kiwify.get("Cart")

        if ordem:
            status = ordem.get("order_status")

            bloco_produto = ordem.get("Product") or ordem.get("product") or {}
            produto = bloco_produto.get("product_name")

            bloco_customer = ordem.get("Customer") or ordem.get("customer") or {}
            nome = bloco_customer.get("full_name") or bloco_customer.get("name")
            email = bloco_customer.get("email")
            telefone = bloco_customer.get("mobile") or bloco_customer.get("phone")

            custom_variables = ordem.get("custom_variables") or ordem.get("CustomVariables") or {}

            if isinstance(custom_variables, dict):
                manychat_user_id = custom_variables.get("manychat_id")

        elif carrinho:
            status = carrinho.get("status")
            produto = carrinho.get("product_name")
            nome = carrinho.get("name") or carrinho.get("full_name")
            email = carrinho.get("email")
            telefone = carrinho.get("phone") or carrinho.get("mobile")

            custom_variables = carrinho.get("custom_variables") or carrinho.get("CustomVariables") or {}

            if isinstance(custom_variables, dict):
                manychat_user_id = custom_variables.get("manychat_id")

        # Se veio src=mc_123456, usa isso como manychat_id quando a Kiwify não mandar custom_variables.
        manychat_id_do_src = extrair_manychat_id_do_src(checkout_src)
        if not manychat_id_valido(manychat_user_id) and manychat_id_valido(manychat_id_do_src):
            manychat_user_id = manychat_id_do_src

        if not email:
            email = dados_kiwify.get("email")

        if not nome:
            nome = dados_kiwify.get("name") or dados_kiwify.get("nome")

        if not telefone:
            telefone = dados_kiwify.get("phone") or dados_kiwify.get("mobile")

        telefone = limpar_telefone(telefone)

        if not email:
            fonte_debug = dados_kiwify.get("data") if isinstance(dados_kiwify.get("data"), dict) else dados_kiwify

            ordem_debug = fonte_debug.get("order") or fonte_debug.get("Order") or fonte_debug
            if not isinstance(ordem_debug, dict):
                ordem_debug = {}

            customer_debug = (
                ordem_debug.get("Customer")
                or ordem_debug.get("customer")
                or fonte_debug.get("Customer")
                or fonte_debug.get("customer")
                or {}
            )
            if not isinstance(customer_debug, dict):
                customer_debug = {}

            product_debug = (
                ordem_debug.get("Product")
                or ordem_debug.get("product")
                or fonte_debug.get("Product")
                or fonte_debug.get("product")
                or {}
            )
            if not isinstance(product_debug, dict):
                product_debug = {}

            email = (
                customer_debug.get("email")
                or customer_debug.get("Email")
                or fonte_debug.get("email")
                or fonte_debug.get("Email")
            )

            nome = (
                nome
                or customer_debug.get("full_name")
                or customer_debug.get("name")
                or customer_debug.get("first_name")
                or fonte_debug.get("full_name")
                or fonte_debug.get("name")
                or fonte_debug.get("nome")
            )

            telefone = (
                telefone
                or customer_debug.get("mobile")
                or customer_debug.get("phone")
                or fonte_debug.get("mobile")
                or fonte_debug.get("phone")
            )

            status = (
                status
                or ordem_debug.get("order_status")
                or ordem_debug.get("webhook_event_type")
                or ordem_debug.get("status")
            )

            produto = (
                produto
                or product_debug.get("product_name")
                or product_debug.get("product_offer_name")
                or product_debug.get("name")
            )

            telefone = limpar_telefone(telefone)

        if not email:
            return {
                "status": "ignorado",
                "detalhe": "JSON sem dados de contato acessiveis",
                "chaves_recebidas": list(dados_kiwify.keys()),
                "tracking_detectado": tracking,
                "origem_compra": origem_compra,
                "payload_recebido": dados_kiwify
            }

        if status:
            status = str(status).strip().lower()

        # Para eventos de abandono, consulta o estado atual antes de gravar.
        # Isso impede webhook atrasado de abandono de sobrescrever um pagamento confirmado.
        lead_existente = None
        if status in STATUS_ABANDONO:
            try:
                lead_existente = buscar_lead_existente(
                    manychat_id=manychat_user_id,
                    telefone=telefone,
                    email=email
                )
            except Exception as e:
                print(f"[Kiwify] Falha ao consultar estado atual antes do abandono: {str(e)}")
                lead_existente = None

            if lead_existente:
                status = status_pagamento_final(
                    lead_existente.get("status_pagamento"),
                    status
                )

        payload_supabase = limpar_payload_supabase({
            "nome": nome,
            "email": email,
            "telefone": telefone,
            "telefone_checkout_kiwify": telefone,
            "status_pagamento": status,
            "produto": produto,
            "checkout_src": tracking.get("checkout_src"),
            "checkout_utm_source": tracking.get("checkout_utm_source"),
            "checkout_utm_medium": tracking.get("checkout_utm_medium"),
            "checkout_utm_campaign": tracking.get("checkout_utm_campaign"),
            "checkout_utm_content": tracking.get("checkout_utm_content"),
            "checkout_utm_term": tracking.get("checkout_utm_term"),
            "origem_compra": origem_compra
        })

        headers_supabase_padrao = obter_headers_supabase(prefer="return=representation")
        headers_supabase_upsert = obter_headers_supabase(
            prefer="resolution=merge-duplicates,return=representation"
        )

        supabase_acao = None
        supabase_code = None
        supabase_resposta = None
        manychat_id_para_tag = None

        if manychat_id_valido(manychat_user_id):
            manychat_user_id = str(manychat_user_id).strip()
            manychat_id_para_tag = manychat_user_id

            payload_supabase["manychat_id"] = manychat_user_id

            response_supabase = requests.post(
                f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id",
                json=payload_supabase,
                headers=headers_supabase_upsert,
                timeout=15
            )

            supabase_acao = "upsert_por_manychat_id"
            supabase_code = response_supabase.status_code
            supabase_resposta = resposta_segura(response_supabase)

        else:
            if not lead_existente:
                lead_existente = buscar_lead_existente(
                    manychat_id=None,
                    telefone=telefone,
                    email=email
                )

            if lead_existente:
                lead_id = lead_existente.get("id")
                id_existente = lead_existente.get("manychat_id")

                if manychat_id_valido(id_existente):
                    manychat_id_para_tag = str(id_existente).strip()

                response_patch = requests.patch(
                    f"{URL}/rest/v1/leads_vigor",
                    params={"id": f"eq.{lead_id}"},
                    json=payload_supabase,
                    headers=headers_supabase_padrao,
                    timeout=15
                )

                supabase_acao = "patch_por_telefone_whatsapp_checkout_ou_email"
                supabase_code = response_patch.status_code
                supabase_resposta = resposta_segura(response_patch)

            else:
                response_insert = requests.post(
                    f"{URL}/rest/v1/leads_vigor",
                    json=payload_supabase,
                    headers=headers_supabase_padrao,
                    timeout=15
                )

                supabase_acao = "insert_novo_lead"
                supabase_code = response_insert.status_code
                supabase_resposta = resposta_segura(response_insert)

        if email and status:
            background_tasks.add_task(gerenciar_tags_convertkit, email, status)

        if status in STATUS_PAGOS:
            headers_mc = obter_headers_manychat()

            if manychat_id_valido(manychat_id_para_tag):
                try:
                    tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"

                    payload_tag = {
                        "subscriber_id": int(str(manychat_id_para_tag).strip()),
                        "tag_name": "comprou-vigor360"
                    }

                    res_tag = requests.post(
                        tag_url,
                        json=payload_tag,
                        headers=headers_mc,
                        timeout=15
                    )

                    return {
                        "status": "sucesso_id_direto",
                        "status_pagamento": status,
                        "email": email,
                        "telefone": telefone,
                        "manychat_id_usado": manychat_id_para_tag,
                        "tracking_detectado": tracking,
                        "origem_compra": origem_compra,
                        "supabase_acao": supabase_acao,
                        "supabase_code": supabase_code,
                        "supabase_resposta": supabase_resposta,
                        "manychat_code": res_tag.status_code,
                        "manychat_resposta": resposta_segura(res_tag)
                    }

                except Exception as e:
                    print(f"[ManyChat] Falha tag ID direto: {str(e)}")

            subscriber_data = []
            find_res = None

            if os.getenv("MANYCHAT_TOKEN"):
                payload_busca = {
                    "field_name": "email",
                    "field_value": email
                }

                find_res = requests.post(
                    "https://api.manychat.com/fb/subscriber/findByCustomField",
                    json=payload_busca,
                    headers=headers_mc,
                    timeout=15
                )

                try:
                    subscriber_data = find_res.json().get("data", [])
                except Exception:
                    subscriber_data = []

                if not subscriber_data and telefone:
                    find_res = requests.get(
                        "https://api.manychat.com/fb/subscriber/findByName",
                        params={"name": telefone},
                        headers=headers_mc,
                        timeout=15
                    )

                    try:
                        dados_find = find_res.json()

                        if isinstance(dados_find, dict) and "data" in dados_find:
                            subscriber_data = dados_find.get("data", [])
                        elif isinstance(dados_find, dict):
                            subscriber_data = [dados_find]
                        else:
                            subscriber_data = []

                    except Exception:
                        subscriber_data = []

                if subscriber_data and isinstance(subscriber_data, list) and len(subscriber_data) > 0:
                    user_info = subscriber_data[0]
                    uid = user_info.get("id")

                    if uid:
                        tag_url = "https://api.manychat.com/fb/subscriber/addTagByName"

                        payload_tag = {
                            "subscriber_id": int(uid),
                            "tag_name": "comprou-vigor360"
                        }

                        res_tag = requests.post(
                            tag_url,
                            json=payload_tag,
                            headers=headers_mc,
                            timeout=15
                        )

                        return {
                            "status": "sucesso_funil_busca",
                            "status_pagamento": status,
                            "email": email,
                            "telefone": telefone,
                            "manychat_id_encontrado": uid,
                            "tracking_detectado": tracking,
                            "origem_compra": origem_compra,
                            "supabase_acao": supabase_acao,
                            "supabase_code": supabase_code,
                            "supabase_resposta": supabase_resposta,
                            "manychat_code": res_tag.status_code,
                            "manychat_resposta": resposta_segura(res_tag)
                        }

            return {
                "status": "comprador_salvo_mas_nao_encontrado_no_manychat",
                "status_pagamento": status,
                "email": email,
                "telefone": telefone,
                "tracking_detectado": tracking,
                "origem_compra": origem_compra,
                "supabase_acao": supabase_acao,
                "supabase_code": supabase_code,
                "supabase_resposta": supabase_resposta,
                "manychat_find_code": find_res.status_code if find_res else None,
                "manychat_find_resposta": resposta_segura(find_res) if find_res else None
            }

        return {
            "status": "processado",
            "status_pagamento": status,
            "email": email,
            "telefone": telefone,
            "supabase_acao": supabase_acao,
            "supabase_code": supabase_code,
            "supabase_resposta": supabase_resposta
        }

    except Exception as e:
        return {
            "status": "erro_critico",
            "detalhe": str(e)
        }


@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE COM RASTREAMENTO DE COMPRA"
