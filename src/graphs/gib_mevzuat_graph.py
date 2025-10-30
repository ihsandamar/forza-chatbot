"""
GIB Mevzuat Araştırma Graph
Gelir İdaresi Başkanlığı mevzuat veritabanında araştırma yapan graph
"""

import json
from typing import List, Dict, Any
from langgraph.graph import StateGraph
from langchain.schema.runnable import RunnableLambda
from langchain.tools import BaseTool
from src.graphs.base_graph import BaseGraph
from src.graphs.registry import register_graph
from src.models.models import LLM, State
from src.tools.gib_mevzuat_tools import get_gib_mevzuat_tools


@register_graph("gib_mevzuat")
class GIBMevzuatGraph(BaseGraph):
    """GIB Mevzuat araştırma graph'ı"""
    
    def __init__(self, llm: LLM):
        super().__init__(llm, State)
        self.tools = get_gib_mevzuat_tools(llm=llm.get_chat())
        self.mevzuat_types = [
            "madde", "gerekce", "bkk", "cbk", "teblig", 
            "yonetmelikler", "genelYazilar", "icGenelge", 
            "ozelge", "sirkuler"
        ]
        
    def extract_keywords_node(self, state: State) -> State:
        """Kullanıcı isteğinden anahtar kelimeleri çıkar"""
        try:
            # Kullanıcı girdisini al
            user_input = self._get_user_input(state)
            
            if not user_input:
                return self._add_error_message(state, "Lütfen aramak istediğiniz konuyu belirtin.")
            
            # Anahtar kelime çıkarma aracını kullan
            keyword_tool = next(tool for tool in self.tools if tool.name == "extract_gib_keywords")
            keywords_json = keyword_tool._run(user_input)
            
            try:
                keywords = json.loads(keywords_json)
                if not isinstance(keywords, list) or not keywords:
                    # Fallback: basit kelime ayırma
                    keywords = self._simple_keyword_extraction(user_input)
                # 5 kelimeye kadar kabul et
                keywords = keywords[:5] if len(keywords) > 5 else keywords
            except Exception as e:
                print(f"JSON parse hatası: {e}, fallback kullanılıyor")
                keywords = self._simple_keyword_extraction(user_input)
            
            # State'e kaydet
            state["search_keywords"] = keywords
            state["original_query"] = user_input
            
            print(f"Çıkarılan anahtar kelimeler: {keywords}")
            
            return state
            
        except Exception as e:
            return self._add_error_message(state, f"Anahtar kelime çıkarma hatası: {str(e)}")
    
    def search_mevzuat_node(self, state: State) -> State:
        """Mevzuat arama yap - çoklu arama terimleri ve türler"""
        try:
            keywords = state.get("search_keywords", [])
            if not keywords:
                return self._add_error_message(state, "Arama için anahtar kelime bulunamadı.")
            
            # Arama aracını al
            search_tool = next(tool for tool in self.tools if tool.name == "gib_mevzuat_search")
            
            all_results = []
            searched_combinations = set()  # Duplicate sonucu engellemek için
            
            # Tüm mevzuat türlerini ara
            all_types = ["genelYazilar", "teblig", "yonetmelikler", "icGenelge", "ozelge", "sirkuler", "madde", "cbk", "bkk"]
            
            # Farklı arama kombinasyonları oluştur
            search_combinations = []
            
            # 1. Tüm kelimeleri birleştir
            full_search = " ".join(keywords[:5]).strip()
            if full_search:
                search_combinations.append(full_search)
            
            # 2. Her bir anahtar kelimeyi ayrı ara
            for keyword in keywords[:3]:
                if keyword and len(keyword.strip()) > 2:
                    search_combinations.append(keyword.strip())
            
            # 3. İkili kombinasyonlar
            if len(keywords) >= 2:
                for i in range(len(keywords)-1):
                    combo = f"{keywords[i]} {keywords[i+1]}"
                    if combo not in search_combinations:
                        search_combinations.append(combo)
            
            # 4. Orijinal query'yi de ekle
            original_query = state.get("original_query", "")
            if original_query and original_query.strip() not in search_combinations:
                search_combinations.append(original_query.strip())
            
            print(f"Arama kombinasyonları: {search_combinations}")
            
            # Her kombinasyon ve mevzuat tipi için arama yap
            for search_term in search_combinations[:4]:  # Maximum 4 kombinasyon
                for mevzuat_type in all_types[:6]:  # Maximum 6 tip
                    combination_key = f"{search_term}_{mevzuat_type}"
                    if combination_key in searched_combinations:
                        continue
                    searched_combinations.add(combination_key)
                    
                    try:
                        print(f"Araniyor: {mevzuat_type} - '{search_term}'")
                        
                        result = search_tool._run(
                            search_terms=search_term,
                            mevzuat_type=mevzuat_type
                        )
                        
                        # JSON formatında sonuç var mı kontrol et
                        if result and result.startswith('[') and result.endswith(']'):
                            try:
                                parsed_results = json.loads(result)
                                if isinstance(parsed_results, list):
                                    for item in parsed_results:
                                        # Duplicate kontrolü - id veya title+tarih ile
                                        item_id = item.get("id", "")
                                        item_signature = f"{item.get('title', '')[:50]}_{item.get('tarih', '')}"
                                        
                                        # Bu sonuç daha önce eklendi mi?
                                        is_duplicate = any(
                                            (existing.get("id") == item_id and item_id) or
                                            f"{existing.get('title', '')[:50]}_{existing.get('tarih', '')}" == item_signature
                                            for existing in all_results
                                        )
                                        
                                        if not is_duplicate:
                                            item["mevzuat_type"] = mevzuat_type
                                            item["search_term_used"] = search_term
                                            all_results.append(item)
                                        
                                    print(f"  -> {len([i for i in parsed_results if not any(e.get('id')==i.get('id') and i.get('id') for e in all_results)])} yeni sonuç bulundu")
                            except json.JSONDecodeError:
                                print(f"  -> JSON parse hatası: {result[:100]}")
                        else:
                            print(f"  -> Sonuç yok")
                        
                        # Yeterli sonuç bulduysak dur
                        if len(all_results) >= 30:
                            print(f"Yeterli sonuç bulundu, arama durduruluyor.")
                            break
                            
                    except Exception as e:
                        print(f"  -> {mevzuat_type} arama hatası: {str(e)}")
                        continue
                
                if len(all_results) >= 30:
                    break
            
            # Sonuçları state'e kaydet
            state["search_results"] = all_results
            
            print(f"Toplam {len(all_results)} benzersiz sonuç bulundu")
            
            return state
            
        except Exception as e:
            return self._add_error_message(state, f"Mevzuat arama hatası: {str(e)}")
    
    def analyze_results_node(self, state: State) -> State:
        """Sonuçları analiz et ve en uygun olanları seç - gelişmiş puanlama sistemi"""
        try:
            results = state.get("search_results", [])
            keywords = state.get("search_keywords", [])
            original_query = state.get("original_query", "")
            
            if not results:
                return self._add_error_message(state, f"'{' '.join(keywords) if keywords else 'Aramanız'}' konusunda mevzuat bulunamadı.")
            
            print(f"Analiz ediliyor: {len(results)} sonuç")
            
            # Tüm sonuçları gelişmiş puanlama ile değerlendir
            for result in results:
                score = 0
                title = result.get("title", "").lower()
                description = result.get("description", "").lower()
                search_term_used = result.get("search_term_used", "").lower()
                mevzuat_type = result.get("mevzuat_type", "")
                
                # 1. Anahtar kelime puanlaması (gelişmiş)
                for keyword in keywords:
                    keyword_lower = keyword.lower().strip()
                    if not keyword_lower or len(keyword_lower) < 2:
                        continue
                        
                    # Başlıkta tam eşleşme (en yüksek puan)
                    if keyword_lower in title:
                        if keyword_lower == title.strip():
                            score += 15  # Tam başlık eşleşmesi
                        elif title.startswith(keyword_lower) or title.endswith(keyword_lower):
                            score += 10  # Baş veya son eşleşme
                        else:
                            score += 7  # Başlık içinde eşleşme
                    
                    # Açıklamada eşleşme
                    if keyword_lower in description:
                        # Hangi konumda eşleştiğine göre puan ver
                        desc_words = description.split()
                        if len(desc_words) > 0:
                            first_quarter = len(desc_words) // 4
                            keyword_positions = [i for i, word in enumerate(desc_words) if keyword_lower in word]
                            
                            if keyword_positions:
                                # Açıklamanın başında eşleşme daha değerli
                                min_pos = min(keyword_positions)
                                if min_pos <= first_quarter:
                                    score += 5
                                else:
                                    score += 3
                    
                    # Kısmi/benzer kelime eşleşmesi
                    if len(keyword_lower) >= 3:
                        title_words = title.split()
                        for word in title_words:
                            if keyword_lower in word or word in keyword_lower:
                                score += 2
                                break
                
                # 2. Orijinal query ile eşleşme
                if original_query:
                    orig_lower = original_query.lower()
                    if orig_lower in title:
                        score += 8
                    elif orig_lower in description:
                        score += 4
                
                # 3. Mevzuat türü önem derecesi
                type_weights = {
                    "genelYazilar": 5,
                    "teblig": 4,
                    "yonetmelikler": 4,
                    "icGenelge": 3,
                    "ozelge": 2,
                    "sirkuler": 2,
                    "madde": 3,
                    "cbk": 2,
                    "bkk": 2
                }
                score += type_weights.get(mevzuat_type, 1)
                
                # 4. Tarih yeniliği ve önemi
                tarih = result.get("tarih", "")
                current_year = 2024
                for year in range(current_year-2, current_year+1):
                    if str(year) in tarih:
                        score += 3  # Son 3 yıl için bonus
                        break
                for year in range(current_year-5, current_year-2):
                    if str(year) in tarih:
                        score += 1  # 3-5 yıl arası için küçük bonus
                        break
                
                # 5. Başlık uzunluğu ve içerik kalitesi
                title_length = len(result.get("title", ""))
                if 20 <= title_length <= 100:  # Optimal uzunluk
                    score += 2
                elif title_length > 100:
                    score += 1
                
                description_length = len(result.get("description", ""))
                if description_length > 100:
                    score += 2  # Detaylı açıklama bonusu
                
                # 6. Kullanılan arama teriminin kalitesi
                if search_term_used and len(search_term_used.split()) > 1:
                    score += 1  # Çoklu kelime araması bonusu
                
                result["relevance_score"] = score
            
            # Puanına göre sırala ve en iyileri al
            results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
            
            # En yüksek puanlı sonucu bul
            max_score = max((r.get("relevance_score", 0) for r in results), default=0)
            
            # Dinamik eşik belirleme
            if max_score > 20:
                threshold = max_score * 0.4  # Yüksek puanlı sonuçlar için çıta yüksek
            elif max_score > 10:
                threshold = max_score * 0.3
            else:
                threshold = max_score * 0.2  # Düşük puanlı sonuçlar için çıta düşük
            
            # Eşiği geçen sonuçları al (maksimum 8)
            top_results = [r for r in results if r.get("relevance_score", 0) >= threshold][:8]
            
            # Hiçbir sonuç eşiği geçmediyse, en yüksek puanlı 5 sonucu al
            if not top_results:
                top_results = results[:5]
            
            # En az 3, en fazla 8 sonuç olsun
            if len(top_results) < 3 and len(results) >= 3:
                top_results = results[:3]
            
            state["top_results"] = top_results
            
            print(f"En alakalı {len(top_results)} sonuç seçildi (Eşik: {threshold:.1f}, Max puan: {max_score})")
            for i, result in enumerate(top_results[:5], 1):
                title_short = result.get('title', 'Başlık yok')[:60]
                score = result.get('relevance_score', 0)
                mev_type = result.get('mevzuat_type', 'N/A')
                print(f"  {i}. {title_short}... (Puan: {score}, Tür: {mev_type})")
            
            return state
            
        except Exception as e:
            return self._add_error_message(state, f"Sonuç analizi hatası: {str(e)}")
    
    def fetch_content_node(self, state: State) -> State:
        """Seçilen sonuçların tam içeriğini al (opsiyonel)"""
        try:
            top_results = state.get("top_results", [])
            
            if not top_results:
                return state
            
            print(f"İçerik detayları alınıyor: {len(top_results)} sonuç")
            
            # İçerik alma aracını al
            content_tool = next((tool for tool in self.tools if tool.name == "gib_content_fetch"), None)
            
            detailed_results = []
            
            for i, result in enumerate(top_results, 1):
                site_link = result.get("siteLink", "")
                
                # İçerik alma işlemini sadece ilk 3 sonuç için yap (performans)
                if i <= 3 and site_link and content_tool:
                    try:
                        print(f"  {i}. İçerik alınıyor: {site_link[:50]}...")
                        
                        content = content_tool._run(site_link)
                        if content and len(content.strip()) > 50:
                            result["full_content"] = content
                            print(f"     -> Başarılı ({len(content)} karakter)")
                        else:
                            result["full_content"] = result.get("description", "İçerik alınamadı")
                            print(f"     -> Kısa içerik, açıklama kullanıldı")
                            
                    except Exception as e:
                        print(f"     -> İçerik alma hatası: {str(e)}")
                        result["full_content"] = result.get("description", "İçerik alınamadı")
                else:
                    # İçerik alınmayan sonuçlar için açıklamayı kullan
                    result["full_content"] = result.get("description", "Açıklama mevcut değil")
                
                detailed_results.append(result)
            
            state["detailed_results"] = detailed_results
            
            return state
            
        except Exception as e:
            print(f"İçerik alma genel hatası: {str(e)}")
            # Hata durumunda top_results'ı detailed_results olarak kullan
            state["detailed_results"] = state.get("top_results", [])
            return state
    
    def generate_summary_node(self, state: State) -> State:
        """Bulunan mevzuatları özetle ve kullanıcıya sun"""
        try:
            detailed_results = state.get("detailed_results", [])
            top_results = state.get("top_results", [])
            original_query = state.get("original_query", "")
            
            # Sonuç yoksa hata mesajı
            if not detailed_results and not top_results:
                return self._add_bot_message(state, "Aramanızla ilgili mevzuat bulunamadı.")
            
            # Mevcut sonuçları kullan
            results_to_use = detailed_results if detailed_results else top_results
            
            # Basit özet oluştur
            summary = f"🎯 KONU: {original_query}\n\n"
            summary += f"📋 BULUNAN MEVZUAT ({len(results_to_use)} adet):\n\n"
            
            for i, result in enumerate(results_to_use, 1):
                title = result.get('title', 'Başlık yok')
                tarih = result.get('tarih', 'Tarih yok')
                kanun_title = result.get('kanunTitle', '')
                kanun_no = result.get('kanunNo', '')
                mevzuat_type = result.get('mevzuat_type', 'Genel')
                site_link = result.get('siteLink', '')
                description = result.get('description', '')[:200]
                
                summary += f"{i}. **{title}**\n"
                summary += f"   📅 Tarih: {tarih}\n"
                if kanun_title:
                    summary += f"   📜 Kanun: {kanun_title}"
                    if kanun_no:
                        summary += f" ({kanun_no})"
                    summary += "\n"
                summary += f"   📂 Tür: {mevzuat_type}\n"
                if description:
                    summary += f"   [NOTE] Açıklama: {description}...\n"
                if site_link:
                    summary += f"   🔗 Link: {site_link}\n"
                summary += "\n"
            
            # Özeti state'e kaydet ve bot mesajı olarak ekle
            state["mevzuat_summary"] = summary
            return self._add_bot_message(state, summary)
            
        except Exception as e:
            return self._add_error_message(state, f"Özet oluşturma hatası: {str(e)}")
    
    def _get_user_input(self, state: State) -> str:
        """State'den kullanıcı girdisini al"""
        # Önce user_query'yi kontrol et
        user_input = state.get("user_query", "")
        
        # Yoksa messages'dan son human mesajını al
        if not user_input:
            messages = state.get("messages", [])
            for message in reversed(messages):
                # Message objectı mı kontrol et
                if hasattr(message, 'type') and message.type == 'human':
                    if hasattr(message, 'content'):
                        if isinstance(message.content, list):
                            # Content list formatı
                            for content_part in message.content:
                                if isinstance(content_part, dict) and content_part.get('type') == 'text':
                                    user_input = content_part.get('text', '')
                                    if user_input.strip():
                                        break
                        elif isinstance(message.content, str):
                            user_input = message.content
                        break
                # String mesaj formatı (eski format)
                elif isinstance(message, str) and not message.startswith('Bot:'):
                    user_input = message
                    break
        
        return user_input.strip() if user_input else ""
    
    def _add_bot_message(self, state: State, message: str) -> State:
        """Bot mesajını doğru formatta ekle"""
        from langchain.schema import AIMessage
        
        messages = state.get("messages", [])
        bot_message = AIMessage(content=message)
        messages.append(bot_message)
        state["messages"] = messages
        
        # Debug: Mesajın doğru eklendiğini kontrol et
        print(f"[DEBUG] GIB Mevzuat - Bot mesajı eklendi: {len(message)} karakter")
        print(f"[DEBUG] GIB Mevzuat - Toplam mesaj sayısı: {len(messages)}")
        print(f"[DEBUG] GIB Mevzuat - Son mesaj content ilk 100 karakter: {message[:100]}...")
        
        return state
    
    def _add_error_message(self, state: State, error: str) -> State:
        """Hata mesajını ekle"""
        return self._add_bot_message(state, f"[ERROR] Hata: {error}")
    
    def _simple_keyword_extraction(self, text: str) -> list:
        """Basit anahtar kelime çıkarma (fallback) - gelişmiş versiyon"""
        import re
        
        # Birleşik terimler sözlüğü
        compound_terms = {
            'ödeme kaydedici cihaz': ['ödeme kaydedici cihaz', 'ökc', 'pos'],
            'kredi kartı': ['kredi kartı', 'pos', 'ödeme'],
            'katma değer vergisi': ['katma değer vergisi', 'kdv', 'vergi'],
            'özel tüketim vergisi': ['özel tüketim vergisi', 'ötv', 'tüketim'],
            'gelir vergisi': ['gelir vergisi', 'gelir', 'vergi'],
            'kurumlar vergisi': ['kurumlar vergisi', 'kurumlar', 'vergi']
        }
        
        # Önemli vergi terimleri
        important_terms = [
            'kdv', 'katma', 'değer', 'vergisi', 'özel', 'tüketim', 'ötv', 'gelir', 'kurumlar',
            'tevkifat', 'stopaj', 'iade', 'istisna', 'muafiyet', 'indirim', 'beyanname',
            'ihracat', 'ithalat', 'fatura', 'belge', 'teşvik', 'matrah', 'oran', 'tarhiyat',
            'ökc', 'pos', 'ödeme', 'kaydedici', 'cihaz', 'kredi', 'kartı', 'akaryakıt',
            'istasyon', 'benzinlik', 'damga', 'harç', 'bsmv', 'banka', 'sigorta'
        ]
        
        # Metni temizle
        text_lower = text.lower()
        text_clean = re.sub(r'[^\w\s]', ' ', text_lower)
        words = text_clean.split()
        
        # Anahtar kelimeleri bul
        keywords = []
        
        # Önce birleşik terimleri ara
        for compound_term, related_terms in compound_terms.items():
            if compound_term in text_lower:
                # Birleşik terimin kendisini ve ilişkili terimlerini ekle
                for term in related_terms[:3]:  # Maksimum 3 ilişkili terim
                    if term not in keywords:
                        keywords.append(term)
                        if len(keywords) >= 5:
                            break
                if len(keywords) >= 5:
                    break
        
        # Önemli terimleri bul
        if len(keywords) < 3:
            for word in words:
                if word in important_terms and word not in keywords:
                    keywords.append(word)
                    if len(keywords) >= 5:
                        break
        
        # Yeterli değilse diğer kelimeleri ekle
        if len(keywords) < 3:
            stop_words = {
                'bir', 'bu', 'da', 'de', 'den', 'ile', 'için', 'mi', 'mu', 'nı', 'nü', 'na', 'ne', 
                'hakkında', 'nasıl', 'nedir', 'olan', 've', 'veya', 'ama', 'fakat', 'şu', 'o'
            }
            for word in words:
                if (len(word) > 2 and 
                    word not in stop_words and 
                    word not in keywords and
                    not word.isdigit()):
                    keywords.append(word)
                    if len(keywords) >= 5:
                        break
        
        return keywords[:5] if keywords else ['mevzuat', 'kanun', 'hüküm', 'düzenleme']
    
    def build_graph(self):
        """Graph'ı oluştur"""
        print("GIB Mevzuat araştırma graph'ı çalıştırılıyor...")
        
        graph = StateGraph(State)
        
        # Node'ları ekle
        graph.add_node("extract_keywords", RunnableLambda(self.extract_keywords_node))
        graph.add_node("search_mevzuat", RunnableLambda(self.search_mevzuat_node))
        graph.add_node("analyze_results", RunnableLambda(self.analyze_results_node))
        graph.add_node("fetch_content", RunnableLambda(self.fetch_content_node))
        graph.add_node("generate_summary", RunnableLambda(self.generate_summary_node))
        
        # Edge'leri tanımla
        graph.set_entry_point("extract_keywords")
        graph.add_edge("extract_keywords", "search_mevzuat")
        graph.add_edge("search_mevzuat", "analyze_results")
        graph.add_edge("analyze_results", "fetch_content")
        graph.add_edge("fetch_content", "generate_summary")
        graph.set_finish_point("generate_summary")
        
        return graph.compile()