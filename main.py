from fastapi import FastAPI, Request
import requests

# 1. Declaramos o app primeiro
app = FastAPI()

# 2. Suas configurações
URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
KEY = "sb_secret_2uwKMoi6Z3mN1mFU1cOKqA_Unq-q5d8" 

# 3. Definimos a rota de recebimento
@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados = await request.json()
        
        # Garante que o ID existe no pacote. 
        # Se o ManyChat enviar 'user_id', nós salvamos como 'id'
        if "user_id" in dados:
            dados["id"] = dados.pop("user_id")
        
        # Se não tiver um 'id' no JSON, o Supabase não tem como fazer o merge.
        # Isso é o que causa as suas linhas NULL.
        if "id" not in dados:
            return {"status": "erro", "detalhe": "ID do lead não encontrado no webhook. O Supabase não pode atualizar sem um ID."}
        
        headers = {
            "apikey": KEY, 
            "Authorization": f"Bearer {KEY}", 
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates" 
        }
        
        # Enviamos para a tabela leads_vigor
        response = requests.post(f"{URL}/rest/v1/leads_vigor", json=dados, headers=headers)
        
        if response.status_code >= 400:
            return {"status": "erro_banco", "detalhe": response.text}

        return {"status": "sucesso"}
        
    except Exception as e:
        return {"status": "erro_script", "detalhe": str(e)}

# 4. Rota de teste
@app.get("/")
def home():
    return "LUCASBOT V3 - ONLINE E OPERANTE"
