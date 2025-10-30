import json
import os
from typing import Dict, List, Any, Optional

class WebPageCatalogGenerator:
    def __init__(self):
        self.catalog = {"web_pages_catalog": []}
        
    def get_user_input(self, prompt: str, required: bool = True, input_type: str = "str") -> Any:
        """Kullanıcıdan input alır ve tip dönüşümlerini yapar"""
        while True:
            try:
                user_input = input(f"{prompt}: ").strip()
                
                if not user_input and required:
                    print("Bu alan zorunludur. Lütfen bir değer girin.")
                    continue
                elif not user_input and not required:
                    return None
                
                if input_type == "str":
                    return user_input
                elif input_type == "bool":
                    return user_input.lower() in ['true', '1', 'yes', 'evet', 'e']
                elif input_type == "int":
                    return int(user_input)
                elif input_type == "list":
                    # Virgülle ayrılmış listeyi parse et
                    return [item.strip() for item in user_input.split(',') if item.strip()]
                
            except ValueError as e:
                print(f"Geçersiz değer: {e}. Tekrar deneyin.")
                
    def get_url_parameters(self) -> Optional[Dict[str, Any]]:
        """URL parametrelerini kullanıcıdan alır"""
        print("\n--- URL Parametreleri ---")
        add_params = self.get_user_input("URL parametreleri eklemek istiyor musunuz? (evet/hayır)", required=False)
        
        if not add_params or add_params.lower() not in ['evet', 'e', 'yes', '1']:
            return None
            
        url_parameters = {}
        
        while True:
            param_name = self.get_user_input("Parametre adı (boş bırakırsanız bitir)", required=False)
            if not param_name:
                break
                
            param_type = self.get_user_input(f"{param_name} parametresinin tipi (string/integer/boolean/guid)", required=True)
            description = self.get_user_input(f"{param_name} parametresinin açıklaması", required=True)
            required = self.get_user_input(f"{param_name} parametresi zorunlu mu? (evet/hayır)", required=True, input_type="bool")
            
            param_data = {
                "type": param_type,
                "description": description,
                "required": required
            }
            
            default_value = self.get_user_input(f"{param_name} parametresinin varsayılan değeri (opsiyonel)", required=False)
            if default_value:
                if param_type == "integer":
                    try:
                        param_data["default"] = int(default_value)
                    except ValueError:
                        param_data["default"] = default_value
                elif param_type == "boolean":
                    param_data["default"] = default_value.lower() in ['true', '1', 'yes', 'evet', 'e']
                else:
                    param_data["default"] = default_value
                    
            url_parameters[param_name] = param_data
            
        return url_parameters if url_parameters else None

    def create_page_entry(self) -> Dict[str, Any]:
        """Tek bir sayfa girişi oluşturur"""
        print("\n" + "="*60)
        print("YENİ SAYFA BİLGİLERİ")
        print("="*60)
        
        # Metadata bilgileri
        print("\n--- Temel Bilgiler ---")
        page_id = self.get_user_input("Page ID")
        url_route = self.get_user_input("URL Route")
        title = self.get_user_input("Sayfa Başlığı")
        category = self.get_user_input("Kategori")
        page_type = self.get_user_input("Sayfa Tipi (main_page/sub_page)")
        
        metadata = {
            "page_id": page_id,
            "url_route": url_route,
            "title": title,
            "category": category,
            "page_type": page_type
        }
        
        # Opsiyonel metadata alanları
        print("\n--- Opsiyonel Bilgiler ---")
        parent_page_id = self.get_user_input("Parent Page ID (opsiyonel)", required=False)
        if parent_page_id:
            metadata["parent_page_id"] = parent_page_id
            
        sub_page_type = self.get_user_input("Sub Page Type (tab/link - opsiyonel)", required=False)
        if sub_page_type:
            metadata["sub_page_type"] = sub_page_type
            
        full_path = self.get_user_input("Full Path (opsiyonel)", required=False)
        if full_path:
            metadata["full_path"] = full_path
            
        # URL parametreleri
        url_parameters = self.get_url_parameters()
        if url_parameters:
            metadata["url_parameters"] = url_parameters
        
        # Content bilgileri
        print("\n--- İçerik Bilgileri ---")
        embedding_content = self.get_user_input("Embedding Content (sayfa açıklaması)")
        
        parent_context = self.get_user_input("Parent Context (opsiyonel)", required=False)
        
        # Structured data
        print("\n--- Yapılandırılmış Veriler ---")
        print("(Virgülle ayırarak giriniz)")
        functions = self.get_user_input("Fonksiyonlar", input_type="list")
        keywords = self.get_user_input("Anahtar Kelimeler", input_type="list")
        related_terms = self.get_user_input("İlgili Terimler", input_type="list")
        user_types = self.get_user_input("Kullanıcı Tipleri", input_type="list")
        
        structured_data = {
            "functions": functions,
            "keywords": keywords,
            "related_terms": related_terms,
            "user_types": user_types
        }
        
        # User expressions
        print("\n--- Kullanıcı İfadeleri ---")
        user_expressions = self.get_user_input("Kullanıcı İfadeleri (virgülle ayırın)", input_type="list")
        
        # Page entry oluştur
        page_entry = {
            "metadata": metadata,
            "embedding_content": embedding_content,
            "structured_data": structured_data,
            "user_expressions": user_expressions
        }
        
        if parent_context:
            page_entry["parent_context"] = parent_context
            
        return page_entry

    def load_existing_catalog(self, filename: str) -> bool:
        """Mevcut katalog dosyasını yükler"""
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    self.catalog = json.load(f)
                print(f"Mevcut katalog yüklendi: {len(self.catalog['web_pages_catalog'])} sayfa")
                return True
            except Exception as e:
                print(f"Katalog yüklenirken hata: {e}")
                return False
        return False

    def save_catalog(self, filename: str) -> bool:
        """Katalogu dosyaya kaydeder"""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.catalog, f, ensure_ascii=False, indent=2)
            print(f"Katalog başarıyla kaydedildi: {filename}")
            return True
        except Exception as e:
            print(f"Katalog kaydedilirken hata: {e}")
            return False

    def display_current_catalog(self):
        """Mevcut katalogu gösterir"""
        if not self.catalog["web_pages_catalog"]:
            print("Henüz hiç sayfa eklenmemiş.")
            return
            
        print(f"\nMevcut Katalog ({len(self.catalog['web_pages_catalog'])} sayfa):")
        print("-" * 60)
        for i, page in enumerate(self.catalog["web_pages_catalog"], 1):
            print(f"{i}. {page['metadata']['title']} (ID: {page['metadata']['page_id']})")

    def run(self):
        """Ana program döngüsü"""
        print("Web Pages Catalog Generator")
        print("=" * 50)
        
        # Mevcut dosyayı yükleme seçeneği
        load_existing = self.get_user_input("Mevcut katalog dosyasını yüklemek istiyor musunuz? (evet/hayır)", required=False)
        
        if load_existing and load_existing.lower() in ['evet', 'e', 'yes', '1']:
            filename = self.get_user_input("Katalog dosyası adı (.json uzantısız)", required=False)
            if not filename:
                filename = "web_catalog"
            if not filename.endswith('.json'):
                filename += '.json'
            self.load_existing_catalog(filename)
        
        # Mevcut katalogu göster
        self.display_current_catalog()
        
        # Yeni sayfalar ekleme
        while True:
            add_page = self.get_user_input("\nYeni sayfa eklemek istiyor musunuz? (evet/hayır)", required=False)
            
            if not add_page or add_page.lower() not in ['evet', 'e', 'yes', '1']:
                break
                
            try:
                page_entry = self.create_page_entry()
                self.catalog["web_pages_catalog"].append(page_entry)
                print(f"\n[CHECK] Sayfa başarıyla eklendi: {page_entry['metadata']['title']}")
                
                # Güncel durumu göster
                self.display_current_catalog()
                
            except KeyboardInterrupt:
                print("\n\nİşlem kullanıcı tarafından iptal edildi.")
                break
            except Exception as e:
                print(f"\nHata oluştu: {e}")
                continue
        
        # Kaydetme
        if self.catalog["web_pages_catalog"]:
            save_file = self.get_user_input("\nKatalogu kaydetmek istiyor musunuz? (evet/hayır)", required=False)
            
            if save_file and save_file.lower() in ['evet', 'e', 'yes', '1']:
                output_filename = self.get_user_input("Çıktı dosyası adı (.json uzantısız)", required=False)
                if not output_filename:
                    output_filename = "web_catalog_output"
                if not output_filename.endswith('.json'):
                    output_filename += '.json'
                    
                self.save_catalog(output_filename)
        
        print("\nProgram tamamlandı!")

def main():
    generator = WebPageCatalogGenerator()
    generator.run()

if __name__ == "__main__":
    main()