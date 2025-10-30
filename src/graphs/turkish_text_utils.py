"""
Turkish text normalization utilities for better matching
"""
import re


def normalize_turkish_text(text: str) -> str:
    """Normalize Turkish text for better matching"""
    if not text:
        return ""

    # Turkish character mappings for normalization
    tr_char_map = {
        'ç': 'c', 'ğ': 'g', 'ı': 'i', 'ş': 's', 'ü': 'u', 'ö': 'o',
        'Ç': 'c', 'Ğ': 'g', 'İ': 'i', 'Ş': 's', 'Ü': 'u', 'Ö': 'o'
    }

    # Apply Turkish character normalization
    normalized = text
    for tr_char, en_char in tr_char_map.items():
        normalized = normalized.replace(tr_char, en_char)

    # Remove extra whitespace and punctuation
    normalized = re.sub(r'[^\w\s]', ' ', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()

    return normalized


def get_keyword_boost(query: str, title: str, category: str) -> float:
    """Apply semantic keyword boosts for better matching"""
    boost = 0

    # Financial/payment keywords
    if any(word in query for word in ['fatura', 'odeme', 'tahsilat', 'kasa', 'banka']):
        if any(word in title for word in ['fatura', 'odeme', 'tahsilat', 'kasa', 'banka', 'satis', 'alis']):
            boost += 0.2
        if 'finans' in category or 'odeme' in category:
            boost += 0.15

    # Customer/CRM keywords
    if any(word in query for word in ['musteri', 'cari', 'firma', 'sirket']):
        if any(word in title for word in ['cari', 'musteri', 'firma']):
            boost += 0.2
        if 'crm' in category or 'cari' in category:
            boost += 0.15

    # Inventory/stock keywords
    if any(word in query for word in ['stok', 'urun', 'envanter', 'mal']):
        if any(word in title for word in ['urun', 'stok', 'hizmet', 'mal']):
            boost += 0.2
        if 'stok' in category or 'urun' in category:
            boost += 0.15

    # Report/analytics keywords
    if any(word in query for word in ['rapor', 'analiz', 'istatistik', 'master']):
        if any(word in title for word in ['rapor', 'master', 'analiz']):
            boost += 0.2
        if 'rapor' in category:
            boost += 0.15

    # Settings/configuration keywords
    if any(word in query for word in ['ayar', 'yapilandirma', 'konfigurasyon', 'sistem']):
        if any(word in title for word in ['ayar', 'yapilandirma', 'sistem']):
            boost += 0.2

    return min(boost, 0.3)  # Cap boost at 0.3