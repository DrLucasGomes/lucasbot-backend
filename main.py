@app.post("/webhook")
async def webhook(request: Request):
    try:
        dados = await request.json()
        
        # Garanta que o 'whatsapp_id' está definido. 
        # Muitas vezes o ManyChat chama isso de 'id' ou 'user_id' no JSON.
        # Ajuste a linha abaixo se o nome do campo for diferente:
        whatsapp_id = dados.get("whatsapp_id") or dados.get("id")
        
        if not whatsapp_id:
            return {"status": "erro", "detalhe": "ID do WhatsApp não encontrado"}
        
        headers = {
            "apikey": KEY, 
            "Authorization": f"Bearer {KEY}", 
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates" 
        }
        
        # O pulo do gato: Enviamos os dados para a tabela.
        # Como o "Prefer: resolution=merge-duplicates" está no header,
        # e o seu "whatsapp_id" é a Primary Key, o Supabase vai 
        # atualizar a linha existente em vez de criar uma nova linha NULL.
        
        response = requests.post(f"{URL}/rest/v1/leads_vigor", json=dados, headers=headers)
        
        if response.status_code >= 400:
            return {"status": "erro_banco", "detalhe": response.text}

        return {"status": "sucesso"}
        
    except Exception as e:
        return {"status": "erro_script", "detalhe": str(e)}
