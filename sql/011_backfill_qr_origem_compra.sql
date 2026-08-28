-- 011_backfill_qr_origem_compra.sql
--
-- Reclassifica compras ja persistidas que vieram de QR Code usando a coluna
-- existente `origem_compra`. Nenhuma coluna nova e criada.
--
-- A migration e idempotente: repetir a execucao mantem o mesmo resultado.

update public.leads_vigor
set origem_compra = case
    when lower(coalesce(checkout_utm_source, '')) = 'youtube'
         or lower(coalesce(checkout_src, '')) like 'qr_yt%'
        then 'youtube_qrcode'

    when lower(coalesce(checkout_utm_source, '')) in ('facebook', 'meta')
         or lower(coalesce(checkout_src, '')) like 'qr_fb%'
        then 'facebook_qrcode'

    when lower(coalesce(checkout_utm_source, '')) = 'instagram'
         or lower(coalesce(checkout_src, '')) like 'qr_ig%'
        then 'instagram_qrcode'

    when lower(coalesce(checkout_utm_source, '')) = 'pdf'
         or lower(coalesce(checkout_src, '')) like 'qr_pdf%'
        then 'pdf_qrcode'

    else 'qrcode_outro'
end
where (
    lower(coalesce(checkout_utm_medium, '')) = 'qrcode'
    or lower(coalesce(checkout_src, '')) like 'qr_%'
)
and lower(coalesce(checkout_utm_source, '')) <> 'manychat'
and lower(coalesce(checkout_src, '')) not like 'mc_%';
