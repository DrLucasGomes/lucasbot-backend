from fastapi import FastAPI, Request, BackgroundTasks
import requests
import os

app = FastAPI()

URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"

CAMPOS_PERMITIDOS = {
    "email", "nome", "telefone", "score", "idade", "risco",
    "status_jornada", "tag", "origem", "campanha",
    "status_testosterona", "tempo_sintoma", "manychat_id",
    "status_pagamento", "produto"
}

CAMPOS_NUMERICOS = {"score", "idade"}


def valor_valido(v):
    return v is not None and str(v).strip() != "" and str(v).strip().lower() not in ["none", "null", "undefined"]


def limpar_telefone(telefone):
    if not valor_valido(telefone):
        return None
    tel = "".join(filter(str.isdigit, str(telefone)))
    return tel if tel else None


def limpar_payload_supabase(dados):
    limpo = {}
    for k, v in dados.items():
        if k not in CAMPOS_PERMITIDOS or not valor_valido(v):
            continue

        if k in CAMPOS_NUMERICOS:
            try:
                limpo[k] = int(str(v).strip())
            except Exception:
                continue
        elif k == "telefone":
            tel = limpar_telefone(v)
            if tel:
                limpo[k] = tel
        else:
            limpo[k] = str(v).strip()

    return limpo


def obter_headers_supabase(prefer=None):
    chave = os.getenv("SUPABASE_KEY")
    headers = {
        "apikey": chave,
        "Authorization": f"Bearer {chave}",
        "Content-Type": "application/json"
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def obter_headers_manychat():
    return {
        "Authorization": f"Bearer {os.getenv('MANYCHAT_TOKEN')}",
        "Content-Type": "application/json"
    }


def resposta_segura(response):
    if response is None:
        return None
    try:
        return response.json()
    except Exception:
        return response.text


def manychat_id_valido(valor):
    return valor_valido(valor)


def gerenciar_tags_convertkit(email: str, status_pagamento: str):
    base_url = "https://api.convertkit.com/v3"
    payload = {
        "api_key": os.getenv("CONVERTKIT_API_KEY"),
        "email": email
    }

    status_pagamento = str(status_pagamento).strip().lower()

    if status_pagamento in ["abandoned", "cart_abandoned"]:
        url = f"{base_url}/tags/{os.getenv('TAG_ABANDONO_ID')}/subscribe"
        try:
            r = requests.post(url, json=payload, timeout=10)
            print(f"[ConvertKit] Abandono aplicado: {email} | {r.status_code} | {r.text}")
        except Exception as e:
            print(f"[ConvertKit Erro] Abandono: {str(e)}")

    elif status_pagamento in ["paid", "approved", "order_approved"]:
        url_add = f"{base_url}/tags/{os.getenv('TAG_COMPRADOR_ID')}/subscribe"
        url_remove = f"{base_url}/tags/{os.getenv('TAG_ABANDONO_ID')}/unsubscribe"
        try:
            r1 = requests.post(url_add, json=payload, timeout=10)
            print(f"[ConvertKit] Comprador aplicado: {email} | {r1.status_code} | {r1.text}")

            if os.getenv("TAG_ABANDONO_ID"):
                r2 = requests.post(url_remove, json=payload, timeout=10)
                print(f"[ConvertKit] Abandono removido: {email} | {r2.status_code} | {r2.text}")
        except Exception as e:
            print(f"[ConvertKit Erro] Comprador: {str(e)}")


@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E BLINDADO"


@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados_brutos = await request.json()

        mc_id = dados_brutos.get("manychat_id")
        if not manychat_id_valido(mc_id):
            return {"status": "erro", "detalhe": "manychat_id nao encontrado"}

        dados_limpos = limpar_payload_supabase(dados_brutos)
        dados_limpos["manychat_id"] = str(mc_id).strip()

        response = requests.post(
            f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id",
            json=dados_limpos,
            headers=obter_headers_supabase("resolution=merge-duplicates,return=representation"),
            timeout=15
        )

        sucesso = response.status_code in [200, 201, 204]

        return {
            "status": "sucesso" if sucesso else "erro_supabase",
            "code": response.status_code,
            "payload_enviado": dados_limpos,
            "resposta_supabase": resposta_segura(response)
        }

    except Exception as e:
        return {"status": "erro_critico", "detalhe": str(e)}


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

        ordem = dados_kiwify.get("order") or dados_kiwify.get("Order") or {}
        carrinho = dados_kiwify.get("cart") or dados_kiwify.get("Cart") or {}

        # ============================================================
        # COMPRA APROVADA / PEDIDO REAL DA KIWIFY
        # ============================================================

        if isinstance(ordem, dict) and ordem:
            status = (
                ordem.get("order_status")
                or ordem.get("webhook_event_type")
                or dados_kiwify.get("status")
            )

            bloco_produto = ordem.get("Product") or ordem.get("product") or {}
            produto = (
                bloco_produto.get("product_name")
                or bloco_produto.get("product_offer_name")
                or ordem.get("product_name")
                or ordem.get("offer_name")
            )

            bloco_customer = ordem.get("Customer") or ordem.get("customer") or {}
            nome = (
                bloco_customer.get("full_name")
                or bloco_customer.get("name")
                or bloco_customer.get("first_name")
            )
            email = bloco_customer.get("email")
            telefone = bloco_customer.get("mobile") or bloco_customer.get("phone")

            custom_variables = (
                ordem.get("custom_variables")
                or ordem.get("CustomVariables")
                or {}
            )

            tracking = ordem.get("TrackingParameters") or ordem.get("tracking_parameters") or {}

            if isinstance(custom_variables, dict):
                manychat_user_id = custom_variables.get("manychat_id")

            if not manychat_user_id and isinstance(tracking, dict):
                manychat_user_id = (
                    tracking.get("manychat_id")
                    or tracking.get("s1")
                    or tracking.get("s2")
                    or tracking.get("s3")
                )

        # ============================================================
        # CARRINHO ABANDONADO REAL DA KIWIFY
        # ============================================================

        elif isinstance(carrinho, dict) and carrinho:
            status = carrinho.get("status")
            produto = carrinho.get("product_name") or carrinho.get("offer_name")
            nome = carrinho.get("name") or carrinho.get("full_name") or carrinho.get("first_name")
            email = carrinho.get("email")
            telefone = carrinho.get("phone") or carrinho.get("mobile")

        # ============================================================
        # FALLBACK GERAL
        # ============================================================

        if not valor_valido(email):
            email = dados_kiwify.get("email")

        if not valor_valido(nome):
            nome = dados_kiwify.get("name") or dados_kiwify.get("nome")

        if not valor_valido(telefone):
            telefone = dados_kiwify.get("phone") or dados_kiwify.get("mobile")

        if not valor_valido(produto):
            produto = dados_kiwify.get("product_name") or dados_kiwify.get("offer_name")

        if not valor_valido(status):
            status = dados_kiwify.get("status") or dados_kiwify.get("webhook_event_type")

        telefone = limpar_telefone(telefone)

        if valor_valido(status):
            status = str(status).strip().lower()

        if valor_valido(email):
            email = str(email).strip()

        if valor_valido(nome):
            nome = str(nome).strip()

        if valor_valido(produto):
            produto = str(produto).strip()

        if not valor_valido(email):
            return {
                "status": "ignorado",
                "detalhe": "JSON sem dados de contato acessiveis",
                "payload_recebido": dados_kiwify
            }

        payload_supabase = limpar_payload_supabase({
            "nome": nome,
            "email": email,
            "telefone": telefone,
            "status_pagamento": status,
            "produto": produto
        })

        headers_padrao = obter_headers_supabase("return=representation")
        headers_upsert = obter_headers_supabase("resolution=merge-duplicates,return=representation")

        supabase_acao = None
        supabase_code = None
        supabase_resposta = None
        manychat_id_para_tag = None

        # ============================================================
        # SALVAR NO SUPABASE
        # ============================================================

        if manychat_id_valido(manychat_user_id):
            manychat_user_id = str(manychat_user_id).strip()
            manychat_id_para_tag = manychat_user_id
            payload_supabase["manychat_id"] = manychat_user_id

            response_supabase = requests.post(
                f"{URL}/rest/v1/leads_vigor?on_conflict=manychat_id",
                json=payload_supabase,
                headers=headers_upsert,
                timeout=15
            )

            supabase_acao = "upsert_por_manychat_id"
            supabase_code = response_supabase.status_code
            supabase_resposta = resposta_segura(response_supabase)

        else:
            lead_existente = None

            if telefone:
                busca_tel = requests.get(
                    f"{URL}/rest/v1/leads_vigor",
                    params={
                        "telefone": f"eq.{telefone}",
                        "select": "id,email,telefone,manychat_id"
                    },
                    headers=obter_headers_supabase(),
                    timeout=15
                )
                if busca_tel.status_code == 200:
                    leads = busca_tel.json()
                    if isinstance(leads, list) and len(leads) > 0:
                        lead_existente = leads[0]

            if not lead_existente and email:
                busca_email = requests.get(
                    f"{URL}/rest/v1/leads_vigor",
                    params={
                        "email": f"eq.{email}",
                        "select": "id,email,telefone,manychat_id"
                    },
                    headers=obter_headers_supabase(),
                    timeout=15
                )
                if busca_email.status_code == 200:
                    leads = busca_email.json()
                    if isinstance(leads, list) and len(leads) > 0:
                        lead_existente = leads[0]

            if lead_existente:
                lead_id = lead_existente.get("id")
                id_existente = lead_existente.get("manychat_id")

                if manychat_id_valido(id_existente):
                    manychat_id_para_tag = str(id_existente).strip()

                response_patch = requests.patch(
                    f"{URL}/rest/v1/leads_vigor",
                    params={"id": f"eq.{lead_id}"},
                    json=payload_supabase,
                    headers=headers_padrao,
                    timeout=15
                )

                supabase_acao = "patch_por_telefone_ou_email"
                supabase_code = response_patch.status_code
                supabase_resposta = resposta_segura(response_patch)

            else:
                response_insert = requests.post(
                    f"{URL}/rest/v1/leads_vigor",
                    json=payload_supabase,
                    headers=headers_padrao,
                    timeout=15
                )

                supabase_acao = "insert_novo_lead"
                supabase_code = response_insert.status_code
                supabase_resposta = resposta_segura(response_insert)

        # ============================================================
        # CONVERTKIT
        # ============================================================

        if email and status:
            background_tasks.add_task(gerenciar_tags_convertkit, email, status)

        # ============================================================
        # MANYCHAT PARA COMPRADOR
        # ============================================================

        if status in ["paid", "approved", "order_approved"]:
            headers_mc = obter_headers_manychat()

            if manychat_id_valido(manychat_id_para_tag):
                try:
                    res_tag = requests.post(
                        "https://api.manychat.com/fb/subscriber/addTagByName",
                        json={
                            "subscriber_id": int(str(manychat_id_para_tag).strip()),
                            "tag_name": "comprou-vigor360"
                        },
                        headers=headers_mc,
                        timeout=15
                    )

                    return {
                        "status": "sucesso_id_direto",
                        "status_pagamento": status,
                        "email": email,
                        "telefone": telefone,
                        "manychat_id_usado": manychat_id_para_tag,
                        "supabase_acao": supabase_acao,
                        "supabase_code": supabase_code,
                        "supabase_resposta": supabase_resposta,
                        "manychat_code": res_tag.status_code,
                        "manychat_resposta": resposta_segura(res_tag)
                    }

                except Exception as e:
                    print(f"[ManyChat] Falha tag ID direto: {str(e)}")

            return {
                "status": "comprador_salvo_mas_nao_encontrado_no_manychat",
                "status_pagamento": status,
                "email": email,
                "telefone": telefone,
                "supabase_acao": supabase_acao,
                "supabase_code": supabase_code,
                "supabase_resposta": supabase_resposta
            }

        return {
            "status": "processado",
            "status_pagamento": status,
            "email": email,
            "telefone": telefone,
            "produto": produto,
            "supabase_acao": supabase_acao,
            "supabase_code": supabase_code,
            "supabase_resposta": supabase_resposta
        }

    except Exception as e:
        return {"status": "erro_critico", "detalhe": str(e)}
