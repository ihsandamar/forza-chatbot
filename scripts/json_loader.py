#!/usr/bin/env python3
"""
VegaForza Web Pages Katalog JSON dosyasını Chroma veritabanına yükler
Minimal Context Inheritance + Separate Indexing yöntemi kullanır
"""

import os
import sys
import json
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
import chromadb
from chromadb.config import Settings
try:
    from langchain_chroma import Chroma
except ImportError:
    from langchain_community.vectorstores import Chroma
from src.services.config_loader import ConfigLoader

def create_main_page_document(page):
    """Ana sayfa için döküman oluştur"""

    # Veri validasyonu
    if not page or not page.get('metadata'):
        raise ValueError("Ana sayfa metadata bilgisi eksik")

    metadata = page['metadata']

    content_parts = [
        f"SAYFA: {metadata.get('title', 'Bilinmeyen Başlık')}",
        f"KATEGORİ: {metadata.get('category', 'unknown')}",
        f"AÇIKLAMA: {page.get('embedding_content', 'Açıklama mevcut değil')}",
        "",
        "KULLANICI İFADELERİ:",
    ]

    # User expressions ekle
    user_expressions = page.get('user_expressions', [])
    if user_expressions:
        for expr in user_expressions:
            content_parts.append(f"- {expr}")
    else:
        content_parts.append("- Kullanıcı ifadeleri mevcut değil")

    content_parts.extend([
        "",
        "FONKSİYONLAR:",
    ])

    # Functions ekle
    structured_data = page.get('structured_data', {})
    functions = structured_data.get('functions', [])
    if functions:
        for func in functions:
            content_parts.append(f"- {func}")
    else:
        content_parts.append("- Fonksiyonlar mevcut değil")

    content_parts.extend([
        "",
        f"ANAHTAR KELİMELER: {', '.join(structured_data.get('keywords', []))}",
        f"İNGİLİZCE TERİMLER: {', '.join(structured_data.get('related_terms', []))}",
        f"KULLANICI TİPLERİ: {', '.join(structured_data.get('user_types', []))}"
    ])

    # URL parametreleri varsa ekle (ana sayfa için de)
    url_parameters = page.get('metadata', {}).get('url_parameters')
    if url_parameters and isinstance(url_parameters, dict) and len(url_parameters) > 0:
        content_parts.extend([
            "",
            "URL PARAMETRELERİ:"
        ])
        for param_name, param_info in url_parameters.items():
            if isinstance(param_info, dict):
                description = param_info.get('description', 'N/A')
                param_type = param_info.get('type', 'N/A')
                required = param_info.get('required', False)
                content_parts.append(f"- {param_name}: {description} (tip: {param_type}, zorunlu: {required})")
            else:
                content_parts.append(f"- {param_name}: {param_info}")

    # Final content
    final_content = "\n".join(content_parts)

    # Metadata hazırla
    metadata = {
        "page_id": page['metadata'].get('page_id', ''),
        "url_route": page['metadata'].get('url_route', ''),
        "title": page['metadata'].get('title', ''),
        "category": page['metadata'].get('category', ''),
        "page_type": page['metadata'].get('page_type', ''),
        "source": "vegaforza_catalog",
        "user_types": ",".join(structured_data.get('user_types', [])),
        "keywords": ",".join(structured_data.get('keywords', [])),
        "document_type": "main_page"
    }

    # URL parametreleri varsa metadata'ya ekle (ana sayfa için de)
    url_parameters = page.get('metadata', {}).get('url_parameters')
    if url_parameters and isinstance(url_parameters, dict) and len(url_parameters) > 0:
        metadata["has_url_parameters"] = "yes"
        try:
            metadata["url_parameters"] = json.dumps(url_parameters, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            print(f"Ana sayfa URL parametreleri JSON'a çevrilemedi: {e}")
            metadata["url_parameters"] = str(url_parameters)
    else:
        metadata["has_url_parameters"] = "no"
        metadata["url_parameters"] = "{}"

    return Document(page_content=final_content, metadata=metadata)

def create_sub_page_document(sub_page, main_page_title, main_page_category):
    """Alt sayfa için döküman oluştur - Minimal Context Inheritance"""

    # Veri validasyonu
    if not sub_page or not sub_page.get('metadata'):
        raise ValueError("Alt sayfa metadata bilgisi eksik")

    metadata = sub_page['metadata']

    # Minimal context inheritance: Sadece temel bilgiyi ekle
    content_parts = [
        f"ALT SAYFA: {metadata.get('title', 'Bilinmeyen Başlık')}",
        f"ANA SAYFA: {main_page_title}",  # Minimal context
        f"KATEGORİ: {metadata.get('category', 'unknown')}",
        f"AÇIKLAMA: {sub_page.get('embedding_content', 'Açıklama mevcut değil')}",
        ""
    ]

    # Parent context ekle (eğer varsa)
    if sub_page.get('parent_context'):
        content_parts.extend([
            f"�ST SAYFA BALAMI: {sub_page['parent_context']}",
            ""
        ])

    # User expressions ekle
    if sub_page.get('user_expressions'):
        content_parts.append("KULLANICI İFADELERİ:")
        for expr in sub_page['user_expressions']:
            content_parts.append(f"- {expr}")
        content_parts.append("")

    # Functions ekle
    if sub_page.get('structured_data', {}).get('functions'):
        content_parts.append("FONKSİYONLAR:")
        for func in sub_page['structured_data']['functions']:
            content_parts.append(f"- {func}")
        content_parts.append("")

    # Keywords ve diğer bilgiler
    structured_data = sub_page.get('structured_data', {})
    if structured_data:
        content_parts.extend([
            f"ANAHTAR KELİMELER: {', '.join(structured_data.get('keywords', []))}",
            f"İNGİLİZCE TERİMLER: {', '.join(structured_data.get('related_terms', []))}",
            f"KULLANICI TİPLERİ: {', '.join(structured_data.get('user_types', []))}"
        ])

    # URL parametreleri varsa ekle
    url_parameters = sub_page.get('metadata', {}).get('url_parameters')
    if url_parameters and isinstance(url_parameters, dict) and len(url_parameters) > 0:
        content_parts.extend([
            "",
            "URL PARAMETRELERİ:"
        ])
        for param_name, param_info in url_parameters.items():
            if isinstance(param_info, dict):
                description = param_info.get('description', 'N/A')
                param_type = param_info.get('type', 'N/A')
                required = param_info.get('required', False)
                content_parts.append(f"- {param_name}: {description} (tip: {param_type}, zorunlu: {required})")
            else:
                content_parts.append(f"- {param_name}: {param_info}")

    # Final content
    final_content = "\n".join(content_parts)

    # Metadata hazırla
    metadata = {
        "page_id": sub_page['metadata'].get('page_id', ''),
        "url_route": sub_page['metadata'].get('url_route', ''),
        "title": sub_page['metadata'].get('title', ''),
        "category": sub_page['metadata'].get('category', ''),
        "page_type": sub_page['metadata'].get('page_type', ''),
        "parent_page_id": sub_page['metadata'].get('parent_page_id', ''),
        "sub_page_type": sub_page['metadata'].get('sub_page_type', ''),
        "full_path": sub_page['metadata'].get('full_path', ''),
        "source": "vegaforza_catalog",
        "user_types": ",".join(structured_data.get('user_types', [])),
        "keywords": ",".join(structured_data.get('keywords', [])),
        "document_type": "sub_page",
        "main_page_title": main_page_title,
        "main_page_category": main_page_category
    }

    # URL parametreleri varsa metadata'ya ekle
    url_parameters = sub_page.get('metadata', {}).get('url_parameters')
    if url_parameters and isinstance(url_parameters, dict) and len(url_parameters) > 0:
        metadata["has_url_parameters"] = "yes"
        try:
            metadata["url_parameters"] = json.dumps(url_parameters, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            print(f"URL parametreleri JSON'a çevrilemedi: {e}")
            metadata["url_parameters"] = str(url_parameters)
    else:
        metadata["has_url_parameters"] = "no"
        metadata["url_parameters"] = "{}"

    return Document(page_content=final_content, metadata=metadata)

def load_json_catalog_to_chroma():
    """JSON katalog dosyasını yükler ve Chroma'ya kaydeder"""

    # Config yükle
    config = ConfigLoader.load_config("config/config.yaml")

    # JSON dosya yolu
    json_path = "data/forza.json"

    if not os.path.exists(json_path):
        print(f"Hata: {json_path} dosyası bulunamadı!")
        print(f"Mevcut dizin: {os.getcwd()}")
        print(f"Aradığımız dosya: {os.path.abspath(json_path)}")
        return False

    print(f"JSON katalog yükleniyor: {json_path}")

    try:
        # JSON dosyasını yükle
        with open(json_path, 'r', encoding='utf-8') as f:
            catalog_data = json.load(f)

        print(f"JSON başarıyla yüklendi. Sayfa sayısı: {len(catalog_data['web_pages_catalog'])}")

        # Separate Indexing: Ana ve alt sayfalar için ayrı dökümanlar
        documents = []
        main_pages = {}  # Ana sayfaları store et

        # İlk geçiş: Ana sayfaları topla
        for page in catalog_data['web_pages_catalog']:
            if page['metadata']['page_type'] == 'main_page':
                main_pages[page['metadata']['page_id']] = page

        # İkinci geçiş: Tüm dökümanları oluştur
        for page in catalog_data['web_pages_catalog']:
            page_type = page['metadata']['page_type']
            # page_type tutarsızlığını düzelt
            if page_type in ['main_page', 'mainpage']:
                # Ana sayfa dökümanı oluştur
                main_doc = create_main_page_document(page)
                documents.append(main_doc)
                print(f"Ana sayfa eklendi: {page['metadata']['title']}")

            elif page_type == 'sub_page':
                # Alt sayfa dökümanı oluştur
                parent_page_id = page['metadata'].get('parent_page_id', '')
                main_page = main_pages.get(parent_page_id, {})
                main_page_title = main_page.get('metadata', {}).get('title', 'Bilinmeyen Ana Sayfa')
                main_page_category = main_page.get('metadata', {}).get('category', 'unknown')

                sub_doc = create_sub_page_document(page, main_page_title, main_page_category)
                documents.append(sub_doc)
                print(f"Alt sayfa eklendi: {page['metadata']['title']} (Ana: {main_page_title})")

        print(f"Toplam {len(documents)} döküman hazırlandı")
        print(f"Ana sayfalar: {len([d for d in documents if d.metadata['document_type'] == 'main_page'])}")
        print(f"Alt sayfalar: {len([d for d in documents if d.metadata['document_type'] == 'sub_page'])}")

        # Text splitter (büyük dökümanlar için)
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=2000,
            chunk_overlap=100,
            separators=["\n\nFONKSİYONLAR:", "\n\nKULLANICI İFADELERİ:", "\n\n", "\n", ".", ","]
        )

        # Sadece çok uzun dökümanları böl
        final_documents = []
        for doc in documents:
            if len(doc.page_content) > 2000:
                splits = text_splitter.split_documents([doc])
                final_documents.extend(splits)
            else:
                final_documents.append(doc)

        print(f"Parçalama sonrası toplam döküman sayısı: {len(final_documents)}")

        # Embedding modeli
        embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=config.llm.api_key,
            base_url=config.llm.base_url,
        )

        # Chroma setup
        chroma_db_path = "data/vector_index/vegaforza_chroma_db"
        collection_name = "vegaforza_web_pages"

        os.makedirs(chroma_db_path, exist_ok=True)

        chroma_client = chromadb.PersistentClient(
            path=chroma_db_path,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )

        # Eğer collection varsa sil ve yeniden oluştur
        try:
            chroma_client.delete_collection(collection_name)
            print(f"Mevcut '{collection_name}' collectionı silindi")
        except:
            pass

        # Yeni collection oluştur
        collection = chroma_client.create_collection(
            name=collection_name,
            metadata={"description": "VegaForza ERP Web Sayfaları Kataloğu - Minimal Context + Separate Indexing"}
        )

        # Chroma vectorstore oluştur
        vectorstore = Chroma(
            client=chroma_client,
            collection_name=collection_name,
            embedding_function=embeddings,
        )

        # Dökümanları hazırla
        texts = [doc.page_content for doc in final_documents]
        metadatas = [doc.metadata for doc in final_documents]

        print("Dökümanlar Chroma'ya ekleniyor...")

        # Dökümanları toplu olarak ekle (batch processing)
        batch_size = 10
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i+batch_size]
            batch_metadatas = metadatas[i:i+batch_size]

            vectorstore.add_texts(
                texts=batch_texts,
                metadatas=batch_metadatas
            )

            print(f"İşlenen: {min(i+batch_size, len(texts))}/{len(texts)}")

        print(f" Başarıyla {len(texts)} döküman parçası Chroma'ya eklendi!")
        print(f"=� Collection: {collection_name}")
        print(f"=� Veritabanı yolu: {chroma_db_path}")
        print(f"=� Toplam döküman sayısı: {collection.count()}")

        # Test query yap
        test_search(vectorstore)

        return True

    except json.JSONDecodeError as e:
        print(f"JSON Parse Hatası: {str(e)}")
        return False
    except Exception as e:
        print(f"Genel Hata: {str(e)}")
        return False

def test_search(vectorstore):
    """Yüklenen veritabanını test et"""
    print("\n=Test sorguları yapılıyor...")

    test_queries = [
        "Şefim master raporlarını görmek istiyorum",
        "Ciro raporu analizi yapmak istiyorum",
        "Personel performansını kontrol etmek istiyorum",
        "Müşteri listesini görmek istiyorum",
        "Cari hesap detaylarını görmek istiyorum",
        "Dinamik raporlar oluşturmak istiyorum",
        "Finans raporlarını analiz etmek istiyorum"
    ]

    for query in test_queries:
        print(f"\nSorgu: '{query}'")
        results = vectorstore.similarity_search_with_score(query, k=3)

        for i, (result, score) in enumerate(results, 1):
            doc_type = result.metadata.get('document_type', 'N/A')
            title = result.metadata.get('title', 'N/A')
            category = result.metadata.get('category', 'N/A')
            print(f"  {i}. [{doc_type}] {title} (kategori: {category}) - Score: {score:.4f}")

            # Alt sayfa ise ana sayfa bilgisini de göster
            if doc_type == 'sub_page':
                main_title = result.metadata.get('main_page_title', 'N/A')
                print(f"      Ana sayfa: {main_title}")

if __name__ == "__main__":
    print("=� VegaForza JSON Katalog -> Chroma yükleme başlıyor...")
    print("=� Metodoloji: Minimal Context Inheritance + Separate Indexing\n")

    success = load_json_catalog_to_chroma()

    if success:
        print("\n İşlem tamamlandı! Artık VegaForza Navigation RAG sistemi kullanılabilir.")
        print("=� Kullanım: Ana ve alt sayfalar ayrı ayrı indekslendi, minimal context inheritance uygulandı.")
        print("=Vector search tüm documents'ta (ana + sub) çalışır.")
    else:
        print("\nL İşlem başarısız! Lütfen hataları kontrol edin.")