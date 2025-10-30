import re
from typing import Optional

def extract_sql_from_response(response_text: str) -> Optional[str]:
    """
    Esnek SQL çıkarıcı - hem tırnak içindeki hem de tırnaksız SQL'leri ayıklar
    
    Args:
        response_text: LLM'den gelen ham yanıt
        
    Returns:
        str: Temizlenmiş SQL sorgusu veya None
    """
    if not response_text:
        return None
        
    # Önce response_text'i temizle
    cleaned_text = response_text.strip()
    
    # ```sql kod bloklarını kontrol et
    sql_match = re.search(r'```sql\s*\n?(.*?)\n?\s*```', cleaned_text, re.DOTALL | re.IGNORECASE)
    if sql_match:
        return sql_match.group(1).strip()
    
    # ``` genel kod bloklarını kontrol et
    code_match = re.search(r'```\s*\n?(.*?)\n?\s*```', cleaned_text, re.DOTALL | re.IGNORECASE)
    if code_match:
        potential_sql = code_match.group(1).strip()
        # SQL anahtar kelimeleri varsa bu bir SQL'dir
        if re.search(r'\b(SELECT|INSERT|UPDATE|DELETE|WITH)\b', potential_sql, re.IGNORECASE):
            return potential_sql
    
    # Tırnak içindeki SQL'leri kontrol et ("SELECT ..." veya 'SELECT ...')
    quoted_sql_patterns = [
        r'"([^"]*(?:SELECT|INSERT|UPDATE|DELETE|WITH)[^"]*)"',
        r"'([^']*(?:SELECT|INSERT|UPDATE|DELETE|WITH)[^']*)'",
    ]
    
    for pattern in quoted_sql_patterns:
        quoted_match = re.search(pattern, cleaned_text, re.DOTALL | re.IGNORECASE)
        if quoted_match:
            return quoted_match.group(1).strip()
    
    # Direkt SQL kontrolü - metnin başında SELECT vb. varsa
    lines = cleaned_text.split('\n')
    sql_lines = []
    found_sql_start = False
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # SQL başlangıcını tespit et
        if not found_sql_start and re.match(r'\b(SELECT|INSERT|UPDATE|DELETE|WITH)\b', line, re.IGNORECASE):
            found_sql_start = True
            sql_lines.append(line)
        elif found_sql_start:
            # Açıklama satırlarını atla
            if not line.startswith('#') and not line.startswith('--') and not line.startswith('//'):
                sql_lines.append(line)
    
    if sql_lines:
        return '\n'.join(sql_lines)
    
    # Son çare: Eğer hiçbir şey bulunamazsa ve metin SQL anahtar kelimesi içeriyorsa direkt döndür
    if re.search(r'\b(SELECT|INSERT|UPDATE|DELETE|WITH)\b', cleaned_text, re.IGNORECASE):
        return cleaned_text
    
    return None