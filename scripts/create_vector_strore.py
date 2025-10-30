#!/usr/bin/env python3
"""
Advanced Indexing Architecture for ERP Navigation System
Multi-layer semantic indexing with contextual embeddings
Fixed ChromaDB metadata compatibility issues
"""
import os
import sys
import json
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.services.config_loader import ConfigLoader
c = ConfigLoader.load_config("config/config.yaml")

import json
import hashlib
from typing import Dict, List, Any, Tuple, Optional, Union
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import numpy as np
from langchain.schema import Document
from langchain_openai import OpenAIEmbeddings
import chromadb
from chromadb.config import Settings
from langchain_chroma import Chroma




@dataclass
class IndexingConfig:
    """Indexing configuration"""
    source_json: str = "data/forza_map.json"
    output_dir: str = "data/vector_index"
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = 1000
    chunk_overlap: int = 100
    enable_hierarchy: bool = True
    enable_context_enrichment: bool = True
    enable_semantic_categorization: bool = True

class MetadataProcessor:
    """ChromaDB compatible metadata processing"""
    
    @staticmethod
    def clean_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Clean metadata for ChromaDB compatibility"""
        cleaned = {}
        
        for key, value in metadata.items():
            if value is None:
                cleaned[key] = ""
                continue
            
            # Convert based on type
            if isinstance(value, (str, int, float, bool)):
                cleaned[key] = value
            elif isinstance(value, dict):
                # Convert dict to JSON string
                try:
                    json_str = json.dumps(value, ensure_ascii=False)
                    # Truncate if too long (ChromaDB has limits)
                    if len(json_str) > 1000:
                        json_str = json_str[:997] + "..."
                    cleaned[f"{key}_json"] = json_str
                    # Also create a simplified version
                    cleaned[f"{key}_type"] = "dict"
                    cleaned[f"{key}_keys"] = ",".join(str(k) for k in value.keys()) if value else ""
                except (TypeError, ValueError) as e:
                    cleaned[f"{key}_error"] = f"serialization_failed: {str(e)[:100]}"
            elif isinstance(value, (list, tuple)):
                # Convert list/tuple to comma-separated string
                try:
                    if not value:
                        cleaned[key] = ""
                    else:
                        # Handle nested structures in lists
                        str_items = []
                        for item in value[:20]:  # Limit to first 20 items
                            if isinstance(item, (dict, list, tuple)):
                                str_items.append(json.dumps(item, ensure_ascii=False)[:100])
                            else:
                                str_items.append(str(item))
                        
                        result_str = ",".join(str_items)
                        if len(result_str) > 1000:
                            result_str = result_str[:997] + "..."
                        cleaned[key] = result_str
                        cleaned[f"{key}_count"] = len(value)
                        cleaned[f"{key}_type"] = "list"
                except Exception as e:
                    cleaned[f"{key}_error"] = f"list_processing_failed: {str(e)[:100]}"
            else:
                # Convert unknown types to string
                try:
                    str_value = str(value)
                    if len(str_value) > 1000:
                        str_value = str_value[:997] + "..."
                    cleaned[f"{key}_str"] = str_value
                    cleaned[f"{key}_original_type"] = type(value).__name__
                except Exception as e:
                    cleaned[f"{key}_error"] = f"conversion_failed: {str(e)[:100]}"
        
        return cleaned
    
    @staticmethod
    def validate_metadata(metadata: Dict[str, Any]) -> bool:
        """Validate that metadata is ChromaDB compatible"""
        try:
            for key, value in metadata.items():
                if not isinstance(key, str):
                    return False
                if not isinstance(value, (str, int, float, bool)):
                    return False
                # Check for excessively long strings
                if isinstance(value, str) and len(value) > 2000:
                    return False
            return True
        except Exception:
            return False

class ContentExtractor:
    """Advanced content extraction with semantic understanding"""
    
    def __init__(self, config: IndexingConfig):
        self.config = config
        self.metadata_processor = MetadataProcessor()
        self.semantic_categories = self._init_semantic_categories()
    
    def _init_semantic_categories(self) -> Dict[str, List[str]]:
        """Initialize semantic category mappings"""
        return {
            "navigation_intent": [
                "görüntüleme", "listeleme", "arama", "filtreleme",
                "görüntüle", "listele", "ara", "filtrele", "bul", "göster"
            ],
            "action_intent": [
                "oluşturma", "ekleme", "düzenleme", "silme", "güncelleme",
                "oluştur", "ekle", "düzenle", "sil", "güncelle", "kaydet"
            ],
            "analysis_intent": [
                "analiz", "rapor", "özet", "karşılaştırma", "trend",
                "analiz et", "raporla", "özetle", "karşılaştır"
            ],
            "configuration_intent": [
                "ayar", "yapılandırma", "konfigürasyon", "parametre",
                "ayarla", "yapılandır", "konfigüre et"
            ]
        }
    
    def extract_main_page_content(self, page: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and enrich main page content with error handling"""
        try:
            metadata = page.get('metadata', {})
            structured_data = page.get('structured_data', {})
            
            # Core content extraction with safe access
            base_content = {
                "title": metadata.get('title', 'Unknown Title'),
                "description": page.get('embedding_content', ''),
                "category": metadata.get('category', 'uncategorized'),
                "page_type": metadata.get('page_type', 'unknown')
            }
            
            # Enhanced content sections
            content_sections = {
                "primary_content": self._build_primary_content(page),
                "functional_content": self._build_functional_content(structured_data),
                "user_intent_content": self._build_user_intent_content(page.get('user_expressions', [])),
                "contextual_content": self._build_contextual_content(metadata, structured_data),
                "semantic_tags": self._extract_semantic_tags(page)
            }
            
            # Metadata enrichment with compatibility check
            enriched_metadata = self._enrich_metadata(metadata, structured_data, content_sections)
            
            return {
                "base_content": base_content,
                "content_sections": content_sections,
                "metadata": enriched_metadata,
                "indexing_priority": self._calculate_indexing_priority(page)
            }
            
        except Exception as e:
            print(f"[WARNING]  Error extracting content from page: {str(e)}")
            # Return minimal valid structure
            return {
                "base_content": {
                    "title": "Error in extraction",
                    "description": f"Content extraction failed: {str(e)[:200]}",
                    "category": "error",
                    "page_type": "error"
                },
                "content_sections": {
                    "primary_content": f"Error: {str(e)}",
                    "functional_content": "",
                    "user_intent_content": "",
                    "contextual_content": "",
                    "semantic_tags": []
                },
                "metadata": {
                    "page_id": "error",
                    "title": "Error in extraction",
                    "category": "error",
                    "page_type": "error",
                    "url_route": "/error",
                    "error": str(e)[:500]
                },
                "indexing_priority": 1
            }
    
    def _build_primary_content(self, page: Dict[str, Any]) -> str:
        """Build primary searchable content"""
        try:
            metadata = page.get('metadata', {})
            parts = [
                f"SAYFA: {metadata.get('title', 'Unknown')}",
                f"AÇIKLAMA: {page.get('embedding_content', '')}",
                f"KATEGORİ: {metadata.get('category', 'uncategorized')}"
            ]
            return "\n".join(part for part in parts if part.split(': ', 1)[1])  # Only include non-empty parts
        except Exception as e:
            return f"Primary content extraction error: {str(e)}"
    
    def _build_functional_content(self, structured_data: Dict[str, Any]) -> str:
        """Build function-focused content"""
        try:
            functions = structured_data.get('functions', [])
            if not functions:
                return ""
            
            parts = ["MEVCUT ÖZELLIKLER VE IŞLEVLER:"]
            for func in functions:
                if isinstance(func, str):
                    enriched_func = self._enrich_function_description(func)
                    parts.append(f"• {enriched_func}")
                else:
                    # Handle non-string function entries
                    parts.append(f"• {str(func)}")
            
            return "\n".join(parts)
        except Exception as e:
            return f"Functional content extraction error: {str(e)}"
    
    def _build_user_intent_content(self, user_expressions: List[str]) -> str:
        """Build user intent-focused content"""
        try:
            if not user_expressions:
                return ""
            
            parts = ["KULLANICI AMAÇLARI VE İSTEKLERİ:"]
            for expr in user_expressions:
                if isinstance(expr, str):
                    intent_category = self._categorize_user_intent(expr)
                    parts.append(f"• [{intent_category}] {expr}")
                else:
                    parts.append(f"• {str(expr)}")
            
            return "\n".join(parts)
        except Exception as e:
            return f"User intent content extraction error: {str(e)}"
    
    def _build_contextual_content(self, metadata: Dict[str, Any], 
                                 structured_data: Dict[str, Any]) -> str:
        """Build context-rich content"""
        try:
            parts = []
            
            # User roles context
            user_types = structured_data.get('user_types', [])
            if user_types and isinstance(user_types, list):
                user_types_str = ', '.join(str(ut) for ut in user_types)
                parts.append(f"HEDEF KULLANICILAR: {user_types_str}")
            
            # Keywords and related terms
            keywords = structured_data.get('keywords', [])
            related_terms = structured_data.get('related_terms', [])
            
            if keywords and isinstance(keywords, list):
                keywords_str = ', '.join(str(kw) for kw in keywords)
                parts.append(f"ANAHTAR KELIMELER: {keywords_str}")
            if related_terms and isinstance(related_terms, list):
                related_str = ', '.join(str(rt) for rt in related_terms)
                parts.append(f"İLGILİ TERIMLER: {related_str}")
            
            # URL context
            url_route = metadata.get('url_route', 'unknown')
            parts.append(f"ERİŞİM YOLU: {url_route}")
            
            return "\n".join(parts)
        except Exception as e:
            return f"Contextual content extraction error: {str(e)}"
    
    def _extract_semantic_tags(self, page: Dict[str, Any]) -> List[str]:
        """Extract semantic tags for better categorization"""
        try:
            tags = set()
            
            # Category-based tags
            metadata = page.get('metadata', {})
            category = metadata.get('category', 'unknown')
            tags.add(f"category:{category}")
            
            # Function-based tags
            structured_data = page.get('structured_data', {})
            functions = structured_data.get('functions', [])
            if isinstance(functions, list):
                for func in functions:
                    func_str = str(func).lower()
                    if any(word in func_str for word in ["rapor", "report"]):
                        tags.add("capability:reporting")
                    if any(word in func_str for word in ["oluştur", "ekle", "create", "add"]):
                        tags.add("capability:creation")
                    if any(word in func_str for word in ["listele", "görüntüle", "list", "view"]):
                        tags.add("capability:viewing")
            
            # User expression-based tags
            user_expressions = page.get('user_expressions', [])
            if isinstance(user_expressions, list):
                for expr in user_expressions:
                    if isinstance(expr, str):
                        intent_category = self._categorize_user_intent(expr)
                        tags.add(f"intent:{intent_category}")
            
            return list(tags)
        except Exception as e:
            print(f"[WARNING]  Error extracting semantic tags: {str(e)}")
            return ["error:semantic_extraction"]
    
    def _enrich_function_description(self, func: str) -> str:
        """Enrich function descriptions with context"""
        if not isinstance(func, str):
            return str(func)
        
        enrichments = {
            "listesi": "görüntüleme ve listeleme",
            "ekleme": "yeni kayıt oluşturma",
            "düzenleme": "mevcut kayıt güncelleme",
            "silme": "kayıt kaldırma",
            "raporu": "analiz ve raporlama"
        }
        
        enriched = func
        for key, value in enrichments.items():
            if key in func.lower():
                enriched = f"{func} ({value})"
                break
        
        return enriched
    
    def _categorize_user_intent(self, expression: str) -> str:
        """Categorize user intent based on expression"""
        if not isinstance(expression, str):
            return "unknown"
            
        expr_lower = expression.lower()
        
        for intent, keywords in self.semantic_categories.items():
            if any(keyword in expr_lower for keyword in keywords):
                return intent.replace("_intent", "")
        
        return "general"
    
    def _enrich_metadata(self, metadata: Dict[str, Any], 
                        structured_data: Dict[str, Any],
                        content_sections: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich metadata for better indexing with ChromaDB compatibility"""
        try:
            # Start with clean base metadata
            enriched = self.metadata_processor.clean_metadata(metadata.copy())
            
            # Add computed fields (all ChromaDB compatible types)
            semantic_tags = content_sections.get('semantic_tags', [])
            searchable_terms = self._extract_searchable_terms(content_sections)
            
            # Calculate metrics
            complexity_score = self._calculate_complexity_score(structured_data)
            user_relevance_score = self._calculate_user_relevance_score(structured_data)
            semantic_weight = self._calculate_semantic_weight(content_sections)
            
            # Add computed fields
            computed_fields = {
                "content_hash": self._calculate_content_hash(content_sections),
                "complexity_score": float(complexity_score),
                "user_relevance_score": float(user_relevance_score),
                "semantic_weight": float(semantic_weight),
                "index_timestamp": datetime.now().isoformat(),
                "function_count": len(structured_data.get('functions', [])),
                "user_expression_count": max(0, len(str(content_sections.get('user_intent_content', '')).split('\n')) - 1),
                "has_semantic_tags": len(semantic_tags) > 0,
                "searchable_terms_count": len(searchable_terms),
                "has_functions": len(structured_data.get('functions', [])) > 0,
                "has_user_expressions": bool(content_sections.get('user_intent_content', '')),
                "content_length": len(str(content_sections.get('primary_content', ''))),
                "indexing_version": "1.0"
            }
            
            # Convert lists to strings for ChromaDB compatibility
            if semantic_tags:
                computed_fields["semantic_tags"] = ",".join(str(tag) for tag in semantic_tags)
            else:
                computed_fields["semantic_tags"] = ""
                
            if searchable_terms:
                computed_fields["searchable_terms"] = ",".join(str(term) for term in searchable_terms[:50])
            else:
                computed_fields["searchable_terms"] = ""
            
            enriched.update(computed_fields)
            
            # Final cleanup and validation
            enriched = self.metadata_processor.clean_metadata(enriched)
            
            # Validate before returning
            if not self.metadata_processor.validate_metadata(enriched):
                print(f"[WARNING]  Metadata validation failed, using minimal metadata")
                return {
                    "page_id": str(metadata.get('page_id', 'unknown')),
                    "title": str(metadata.get('title', 'Unknown'))[:200],
                    "category": str(metadata.get('category', 'unknown')),
                    "page_type": str(metadata.get('page_type', 'unknown')),
                    "index_timestamp": datetime.now().isoformat(),
                    "error": "metadata_validation_failed"
                }
            
            return enriched
            
        except Exception as e:
            print(f"[WARNING]  Error enriching metadata: {str(e)}")
            # Return minimal safe metadata
            return {
                "page_id": str(metadata.get('page_id', 'error')),
                "title": str(metadata.get('title', 'Error'))[:200],
                "category": "error",
                "page_type": "error",
                "index_timestamp": datetime.now().isoformat(),
                "error": str(e)[:200]
            }
    
    def _calculate_content_hash(self, content_sections: Dict[str, Any]) -> str:
        """Calculate content hash for change detection"""
        try:
            content_str = json.dumps(content_sections, sort_keys=True, ensure_ascii=False)
            return hashlib.sha256(content_str.encode('utf-8')).hexdigest()[:16]
        except Exception as e:
            return f"hash_error_{hash(str(content_sections))}"[:16]
    
    def _calculate_complexity_score(self, structured_data: Dict[str, Any]) -> float:
        """Calculate page complexity for ranking"""
        try:
            base_score = 1.0
            
            # More functions = higher complexity
            functions = structured_data.get('functions', [])
            function_count = len(functions) if isinstance(functions, list) else 0
            complexity_score = base_score + (function_count * 0.1)
            
            # More user types = higher complexity
            user_types = structured_data.get('user_types', [])
            user_type_count = len(user_types) if isinstance(user_types, list) else 0
            complexity_score += (user_type_count * 0.05)
            
            return min(complexity_score, 3.0)  # Cap at 3.0
        except Exception:
            return 1.0
    
    def _calculate_user_relevance_score(self, structured_data: Dict[str, Any]) -> float:
        """Calculate user relevance based on user types and keywords"""
        try:
            base_score = 0.5
            
            # Common user types get higher relevance
            common_types = {'admin', 'user', 'manager', 'accounting'}
            user_types = structured_data.get('user_types', [])
            if isinstance(user_types, list):
                user_types_set = set(str(ut).lower() for ut in user_types)
                common_intersection = user_types_set.intersection(common_types)
                relevance_score = base_score + (len(common_intersection) * 0.2)
            else:
                relevance_score = base_score
                
            return min(relevance_score, 1.0)
        except Exception:
            return 0.5
    
    def _calculate_semantic_weight(self, content_sections: Dict[str, Any]) -> float:
        """Calculate semantic importance weight"""
        try:
            weight = 1.0
            
            # Pages with more content sections get higher weight
            section_count = len([s for s in content_sections.values() if s])
            weight += (section_count - 1) * 0.1
            
            # Pages with semantic tags get boost
            semantic_tags = content_sections.get('semantic_tags', [])
            if isinstance(semantic_tags, list):
                weight += len(semantic_tags) * 0.05
            
            return weight
        except Exception:
            return 1.0
    
    def _extract_searchable_terms(self, content_sections: Dict[str, Any]) -> List[str]:
        """Extract key searchable terms"""
        try:
            terms = set()
            
            # Extract from all content sections
            for section_content in content_sections.values():
                if isinstance(section_content, str):
                    # Simple term extraction (could be enhanced with NLP)
                    words = section_content.lower().split()
                    # Filter meaningful terms (length > 2, not common words)
                    meaningful_terms = [
                        word for word in words 
                        if len(word) > 2 and word not in {'için', 'olan', 'ile', 'bir', 'bu', 'şu', 'the', 'and', 'or'}
                    ]
                    terms.update(meaningful_terms[:10])  # Limit terms per section
            
            return list(terms)[:50]  # Limit total terms
        except Exception:
            return []
    
    def _calculate_indexing_priority(self, page: Dict[str, Any]) -> int:
        """Calculate indexing priority (1-5, 5 = highest)"""
        try:
            priority = 3  # Default
            
            metadata = page.get('metadata', {})
            structured_data = page.get('structured_data', {})
            
            # Main pages get higher priority
            if metadata.get('page_type') == 'main_page':
                priority += 1
            
            # Pages with many functions get higher priority  
            functions = structured_data.get('functions', [])
            function_count = len(functions) if isinstance(functions, list) else 0
            if function_count > 5:
                priority += 1
            elif function_count > 10:
                priority += 2
            
            # Essential categories get boost
            essential_categories = {'accounting', 'reports', 'users', 'settings'}
            if metadata.get('category', '').lower() in essential_categories:
                priority += 1
            
            return min(priority, 5)
        except Exception:
            return 3

class MultiLevelEmbeddingGenerator:
    """Generate multiple embedding levels for different search scenarios"""
    
    def __init__(self, config: IndexingConfig):
        self.config = config
        try:
            self.embeddings = OpenAIEmbeddings(
                model=config.embedding_model,
                openai_api_key=c.llm.api_key,
                base_url=c.llm.base_url,
            )
        except Exception as e:
            print(f"[WARNING]  Error initializing embeddings: {str(e)}")
            self.embeddings = None
    
    def generate_multi_level_embeddings(self, extracted_content: Dict[str, Any]) -> Dict[str, Any]:
        """Generate embeddings at multiple semantic levels"""
        if not self.embeddings:
            print("[WARNING]  Embeddings not available, returning empty embeddings")
            return {
                "primary_embedding": [],
                "functional_embedding": [],
                "user_intent_embedding": [],
                "contextual_embedding": [],
                "combined_embedding": []
            }
        
        try:
            content_sections = extracted_content['content_sections']
            
            embeddings_result = {
                "primary_embedding": self._generate_primary_embedding(content_sections),
                "functional_embedding": self._generate_functional_embedding(content_sections),
                "user_intent_embedding": self._generate_user_intent_embedding(content_sections),
                "contextual_embedding": self._generate_contextual_embedding(content_sections),
                "combined_embedding": None  # Will be computed
            }
            
            # Generate combined embedding
            embeddings_result["combined_embedding"] = self._generate_combined_embedding(
                extracted_content, embeddings_result
            )
            
            return embeddings_result
        except Exception as e:
            print(f"[WARNING]  Error generating embeddings: {str(e)}")
            return {
                "primary_embedding": [],
                "functional_embedding": [],
                "user_intent_embedding": [],
                "contextual_embedding": [],
                "combined_embedding": []
            }
    
    def _generate_primary_embedding(self, content_sections: Dict[str, Any]) -> List[float]:
        """Primary content embedding for general search"""
        try:
            primary_content = content_sections.get('primary_content', '')
            if not primary_content or not isinstance(primary_content, str):
                return []
            
            return self.embeddings.embed_query(primary_content)
        except Exception as e:
            print(f"[WARNING]  Error generating primary embedding: {str(e)}")
            return []
    
    def _generate_functional_embedding(self, content_sections: Dict[str, Any]) -> List[float]:
        """Function-focused embedding for feature discovery"""
        try:
            functional_content = content_sections.get('functional_content', '')
            if not functional_content or not isinstance(functional_content, str):
                return []
            
            return self.embeddings.embed_query(functional_content)
        except Exception as e:
            print(f"[WARNING]  Error generating functional embedding: {str(e)}")
            return []
    
    def _generate_user_intent_embedding(self, content_sections: Dict[str, Any]) -> List[float]:
        """User intent embedding for natural language queries"""
        try:
            user_intent_content = content_sections.get('user_intent_content', '')
            if not user_intent_content or not isinstance(user_intent_content, str):
                return []
            
            return self.embeddings.embed_query(user_intent_content)
        except Exception as e:
            print(f"[WARNING]  Error generating user intent embedding: {str(e)}")
            return []
    
    def _generate_contextual_embedding(self, content_sections: Dict[str, Any]) -> List[float]:
        """Contextual embedding for metadata-rich search"""
        try:
            contextual_content = content_sections.get('contextual_content', '')
            if not contextual_content or not isinstance(contextual_content, str):
                return []
            
            return self.embeddings.embed_query(contextual_content)
        except Exception as e:
            print(f"[WARNING]  Error generating contextual embedding: {str(e)}")
            return []
    
    def _generate_combined_embedding(self, extracted_content: Dict[str, Any], 
                                   embeddings: Dict[str, Any]) -> List[float]:
        """Generate weighted combined embedding"""
        try:
            # Combine all content with semantic weights
            content_parts = []
            weights = {
                'primary_content': 0.4,
                'functional_content': 0.25,
                'user_intent_content': 0.25,
                'contextual_content': 0.1
            }
            
            content_sections = extracted_content['content_sections']
            semantic_weight = extracted_content['metadata'].get('semantic_weight', 1.0)
            
            for section, weight in weights.items():
                content = content_sections.get(section, '')
                if content and isinstance(content, str):
                    # Apply semantic weighting
                    repetitions = max(1, int(weight * semantic_weight * 2))
                    weighted_content = f"{content} " * repetitions
                    content_parts.append(weighted_content)
            
            combined_content = "\n".join(content_parts)
            if not combined_content:
                return []
            
            return self.embeddings.embed_query(combined_content)
        except Exception as e:
            print(f"[WARNING]  Error generating combined embedding: {str(e)}")
            return []

class HierarchicalIndexBuilder:
    """Build hierarchical index structure"""
    
    def __init__(self, config: IndexingConfig):
        self.config = config
        self.content_extractor = ContentExtractor(config)
        self.embedding_generator = MultiLevelEmbeddingGenerator(config)
    
    def build_hierarchical_index(self, json_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build complete hierarchical index"""
        
        pages = json_data.get('web_pages_catalog', [])
        print(f"[ROCKET] Building hierarchical index for {len(pages)} pages...")
        
        # Phase 1: Content extraction and enrichment
        print("[NOTE] Phase 1: Content extraction and enrichment...")
        extracted_pages = []
        
        for i, page in enumerate(pages):
            try:
                page_title = page.get('metadata', {}).get('title', f'Page {i+1}')
                print(f"   Processing page {i+1}/{len(pages)}: {page_title}")
                
                extracted_content = self.content_extractor.extract_main_page_content(page)
                extracted_content['original_page'] = page
                extracted_pages.append(extracted_content)
            except Exception as e:
                print(f"[WARNING]  Error processing page {i+1}: {str(e)}")
                continue
        
        # Phase 2: Multi-level embedding generation
        print("🔮 Phase 2: Multi-level embedding generation...")
        indexed_pages = []
        
        for i, extracted_page in enumerate(extracted_pages):
            try:
                print(f"   Generating embeddings {i+1}/{len(extracted_pages)}")
                
                embeddings = self.embedding_generator.generate_multi_level_embeddings(extracted_page)
                
                indexed_page = {
                    "content": extracted_page,
                    "embeddings": embeddings,
                    "index_metadata": {
                        "indexed_at": datetime.now().isoformat(),
                        "index_version": "1.0",
                        "embedding_model": self.config.embedding_model
                    }
                }
                
                indexed_pages.append(indexed_page)
            except Exception as e:
                print(f"[WARNING]  Error generating embeddings for page {i+1}: {str(e)}")
                continue
        
        # Phase 3: Build hierarchical structure
        print("🏗️  Phase 3: Building hierarchical structure...")
        hierarchical_index = self._build_hierarchy(indexed_pages)
        
        print(f"[OK] Hierarchical index built successfully!")
        print(f"   [CHART] Total pages indexed: {len(indexed_pages)}")
        main_page_count = len([p for p in indexed_pages if p['content']['base_content']['page_type'] == 'main_page'])
        sub_page_count = len([p for p in indexed_pages if p['content']['base_content']['page_type'] == 'sub_page'])
        print(f"   🏠 Main pages: {main_page_count}")
        print(f"   📄 Sub pages: {sub_page_count}")
        
        return hierarchical_index
    
    def _build_hierarchy(self, indexed_pages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build hierarchical relationships"""
        
        hierarchy = {
            "main_pages": {},
            "sub_pages": {},
            "relationships": {},
            "categories": {},
            "semantic_clusters": {}
        }
        
        # Organize by page type
        for indexed_page in indexed_pages:
            try:
                page_type = indexed_page['content']['base_content']['page_type']
                original_page = indexed_page['content'].get('original_page', {})
                page_id = original_page.get('metadata', {}).get('page_id', f"unknown_{hash(str(indexed_page))}")
                
                if page_type == 'main_page':
                    hierarchy["main_pages"][page_id] = indexed_page
                else:
                    hierarchy["sub_pages"][page_id] = indexed_page
            except Exception as e:
                print(f"[WARNING]  Error organizing page in hierarchy: {str(e)}")
                continue
        
        # Build parent-child relationships
        for page_id, sub_page in hierarchy["sub_pages"].items():
            try:
                original_page = sub_page['content'].get('original_page', {})
                parent_id = original_page.get('metadata', {}).get('parent_page_id')
                if parent_id and parent_id in hierarchy["main_pages"]:
                    if parent_id not in hierarchy["relationships"]:
                        hierarchy["relationships"][parent_id] = []
                    hierarchy["relationships"][parent_id].append(page_id)
            except Exception as e:
                print(f"[WARNING]  Error building relationships: {str(e)}")
                continue
        
        # Group by categories
        for page_id, indexed_page in {**hierarchy["main_pages"], **hierarchy["sub_pages"]}.items():
            try:
                category = indexed_page['content']['base_content']['category']
                if category not in hierarchy["categories"]:
                    hierarchy["categories"][category] = []
                hierarchy["categories"][category].append(page_id)
            except Exception as e:
                print(f"[WARNING]  Error grouping by categories: {str(e)}")
                continue
        
        return hierarchy

class OptimizedVectorStore:
    """Optimized vector store with multiple collections"""
    
    def __init__(self, config: IndexingConfig):
        self.config = config
        self.chroma_client = None
        self._initialize_chroma()
    
    def _initialize_chroma(self):
        """Initialize ChromaDB client"""
        try:
            db_path = Path(self.config.output_dir) / "chroma_db"
            db_path.mkdir(parents=True, exist_ok=True)
            
            self.chroma_client = chromadb.PersistentClient(
                path=str(db_path),
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            print("[OK] ChromaDB initialized successfully")
        except Exception as e:
            print(f"[WARNING]  Error initializing ChromaDB: {str(e)}")
            self.chroma_client = None
    
    def create_optimized_collections(self, hierarchical_index: Dict[str, Any]) -> Dict[str, Any]:
        """Create optimized collection structure"""
        
        if not self.chroma_client:
            print("[WARNING]  ChromaDB not available, skipping collection creation")
            return {}
        
        collections = {}
        
        try:
            # Collection 1: Primary search (combined embeddings)
            print("🗂️  Creating primary search collection...")
            primary_collection = self._create_primary_collection(hierarchical_index)
            if primary_collection:
                collections['primary_search'] = primary_collection
            
            # Collection 2: Function discovery (functional embeddings)  
            print("🔧 Creating function discovery collection...")
            function_collection = self._create_function_collection(hierarchical_index)
            if function_collection:
                collections['function_discovery'] = function_collection
            
            # Collection 3: User intent (user intent embeddings)
            print("👤 Creating user intent collection...")
            intent_collection = self._create_intent_collection(hierarchical_index)
            if intent_collection:
                collections['user_intent'] = intent_collection
            
            print(f"[OK] Created {len(collections)} optimized collections")
        except Exception as e:
            print(f"[WARNING]  Error creating collections: {str(e)}")
        
        return collections
    
    def _create_primary_collection(self, hierarchical_index: Dict[str, Any]) -> Any:
        """Create primary search collection with combined embeddings"""
        
        try:
            collection_name = "vegaforza_primary_search"
            
            # Delete existing collection
            try:
                self.chroma_client.delete_collection(collection_name)
            except:
                pass
            
            # Create new collection
            collection = self.chroma_client.create_collection(
                name=collection_name,
                metadata={"description": "Primary search with combined embeddings"}
            )
            
            # Add documents
            all_pages = {**hierarchical_index["main_pages"], **hierarchical_index["sub_pages"]}
            
            documents = []
            embeddings = []
            metadatas = []
            ids = []
            
            for page_id, indexed_page in all_pages.items():
                try:
                    # Combined content for primary search
                    content_sections = indexed_page['content']['content_sections']
                    combined_content_parts = []
                    
                    for key in ['primary_content', 'functional_content', 'user_intent_content', 'contextual_content']:
                        content = content_sections.get(key, '')
                        if content and isinstance(content, str):
                            combined_content_parts.append(content)
                    
                    combined_content = "\n\n".join(combined_content_parts)
                    if not combined_content:
                        continue
                    
                    # Get embedding
                    combined_embedding = indexed_page['embeddings']['combined_embedding']
                    if not combined_embedding:
                        continue
                    
                    documents.append(combined_content)
                    embeddings.append(combined_embedding)
                    
                    # Rich metadata (ensure ChromaDB compatibility)
                    metadata = indexed_page['content']['metadata'].copy()
                    
                    # Additional collection-specific metadata
                    metadata.update({
                        'collection_type': 'primary_search',
                        'content_sections_available': ",".join([
                            key for key in content_sections.keys() 
                            if content_sections.get(key)
                        ]) if content_sections else "",
                        'has_functional_content': bool(content_sections.get('functional_content')),
                        'has_user_intent_content': bool(content_sections.get('user_intent_content')),
                        'content_char_length': len(combined_content)
                    })
                    
                    # Final metadata cleaning
                    cleaned_metadata = MetadataProcessor.clean_metadata(metadata)
                    
                    # Validate metadata
                    if not MetadataProcessor.validate_metadata(cleaned_metadata):
                        print(f"[WARNING]  Skipping page {page_id} due to metadata validation failure")
                        continue
                    
                    metadatas.append(cleaned_metadata)
                    ids.append(f"primary_{page_id}")
                    
                except Exception as e:
                    print(f"[WARNING]  Error processing page {page_id} for primary collection: {str(e)}")
                    continue
            
            if not documents:
                print("[WARNING]  No valid documents to add to primary collection")
                return None
            
            # Batch add to collection
            batch_size = 50
            for i in range(0, len(documents), batch_size):
                try:
                    batch_docs = documents[i:i+batch_size]
                    batch_embeddings = embeddings[i:i+batch_size]
                    batch_metadata = metadatas[i:i+batch_size]
                    batch_ids = ids[i:i+batch_size]
                    
                    collection.add(
                        documents=batch_docs,
                        embeddings=batch_embeddings,
                        metadatas=batch_metadata,
                        ids=batch_ids
                    )
                    
                    print(f"   Added batch {i//batch_size + 1}/{(len(documents) + batch_size - 1)//batch_size}")
                except Exception as e:
                    print(f"[WARNING]  Error adding batch {i//batch_size + 1}: {str(e)}")
                    continue
            
            return collection
            
        except Exception as e:
            print(f"[WARNING]  Error creating primary collection: {str(e)}")
            return None
    
    def _create_function_collection(self, hierarchical_index: Dict[str, Any]) -> Any:
        """Create function discovery collection"""
        
        try:
            collection_name = "vegaforza_function_discovery"
            
            try:
                self.chroma_client.delete_collection(collection_name)
            except:
                pass
            
            collection = self.chroma_client.create_collection(
                name=collection_name,
                metadata={"description": "Function discovery with functional embeddings"}
            )
            
            # Add only pages with functional content
            all_pages = {**hierarchical_index["main_pages"], **hierarchical_index["sub_pages"]}
            
            documents = []
            embeddings = []
            metadatas = []
            ids = []
            
            for page_id, indexed_page in all_pages.items():
                try:
                    functional_content = indexed_page['content']['content_sections'].get('functional_content', '')
                    functional_embedding = indexed_page['embeddings'].get('functional_embedding', [])
                    
                    if not functional_content or not functional_embedding or not isinstance(functional_content, str):
                        continue
                    
                    documents.append(functional_content)
                    embeddings.append(functional_embedding)
                    
                    metadata = indexed_page['content']['metadata'].copy()
                    metadata.update({
                        'collection_type': 'function_discovery',
                        'focus': 'functional_capabilities'
                    })
                    
                    # Clean and validate metadata
                    cleaned_metadata = MetadataProcessor.clean_metadata(metadata)
                    if not MetadataProcessor.validate_metadata(cleaned_metadata):
                        continue
                    
                    metadatas.append(cleaned_metadata)
                    ids.append(f"function_{page_id}")
                    
                except Exception as e:
                    print(f"[WARNING]  Error processing page {page_id} for function collection: {str(e)}")
                    continue
            
            # Batch add
            if documents:
                try:
                    collection.add(
                        documents=documents,
                        embeddings=embeddings,
                        metadatas=metadatas,
                        ids=ids
                    )
                    print(f"   Function collection: {len(documents)} documents")
                except Exception as e:
                    print(f"[WARNING]  Error adding documents to function collection: {str(e)}")
                    return None
            else:
                print("[WARNING]  No functional content found for function collection")
            
            return collection
            
        except Exception as e:
            print(f"[WARNING]  Error creating function collection: {str(e)}")
            return None
    
    def _create_intent_collection(self, hierarchical_index: Dict[str, Any]) -> Any:
        """Create user intent collection"""
        
        try:
            collection_name = "vegaforza_user_intent"
            
            try:
                self.chroma_client.delete_collection(collection_name)
            except:
                pass
            
            collection = self.chroma_client.create_collection(
                name=collection_name,
                metadata={"description": "User intent with natural language understanding"}
            )
            
            # Add pages with user intent content
            all_pages = {**hierarchical_index["main_pages"], **hierarchical_index["sub_pages"]}
            
            documents = []
            embeddings = []
            metadatas = []
            ids = []
            
            for page_id, indexed_page in all_pages.items():
                try:
                    intent_content = indexed_page['content']['content_sections'].get('user_intent_content', '')
                    intent_embedding = indexed_page['embeddings'].get('user_intent_embedding', [])
                    
                    if not intent_content or not intent_embedding or not isinstance(intent_content, str):
                        continue
                    
                    documents.append(intent_content)
                    embeddings.append(intent_embedding)
                    
                    metadata = indexed_page['content']['metadata'].copy()
                    metadata.update({
                        'collection_type': 'user_intent',
                        'focus': 'natural_language_queries'
                    })
                    
                    # Clean and validate metadata
                    cleaned_metadata = MetadataProcessor.clean_metadata(metadata)
                    if not MetadataProcessor.validate_metadata(cleaned_metadata):
                        continue
                    
                    metadatas.append(cleaned_metadata)
                    ids.append(f"intent_{page_id}")
                    
                except Exception as e:
                    print(f"[WARNING]  Error processing page {page_id} for intent collection: {str(e)}")
                    continue
            
            # Batch add
            if documents:
                try:
                    collection.add(
                        documents=documents,
                        embeddings=embeddings,
                        metadatas=metadatas,
                        ids=ids
                    )
                    print(f"   Intent collection: {len(documents)} documents")
                except Exception as e:
                    print(f"[WARNING]  Error adding documents to intent collection: {str(e)}")
                    return None
            else:
                print("[WARNING]  No intent content found for intent collection")
            
            return collection
            
        except Exception as e:
            print(f"[WARNING]  Error creating intent collection: {str(e)}")
            return None

class IndexingOrchestrator:
    """Main orchestrator for the indexing process"""
    
    def __init__(self, config: IndexingConfig):
        self.config = config
        self.hierarchical_builder = HierarchicalIndexBuilder(config)
        self.vector_store = OptimizedVectorStore(config)
    
    def run_full_indexing_pipeline(self) -> Dict[str, Any]:
        """Run the complete indexing pipeline"""
        
        print("[ROCKET] Starting Advanced ERP Navigation Indexing Pipeline")
        print("=" * 60)
        
        try:
            # Load source JSON
            print("📂 Loading source JSON...")
            if not os.path.exists(self.config.source_json):
                raise FileNotFoundError(f"Source JSON file not found: {self.config.source_json}")
            
            with open(self.config.source_json, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            
            if 'web_pages_catalog' not in json_data:
                raise ValueError("Invalid JSON structure: 'web_pages_catalog' not found")
            
            print(f"[OK] Loaded {len(json_data['web_pages_catalog'])} pages from JSON")
            
            # Build hierarchical index
            hierarchical_index = self.hierarchical_builder.build_hierarchical_index(json_data)
            
            # Create optimized vector collections
            collections = self.vector_store.create_optimized_collections(hierarchical_index)
            
            # Generate index statistics
            stats = self._generate_index_statistics(hierarchical_index, collections)
            
            print("\n" + "=" * 60)
            print("🎉 Advanced Indexing Pipeline Completed Successfully!")
            print(f"[CHART] Index Statistics:")
            for key, value in stats.items():
                print(f"   {key}: {value}")
            
            return {
                "hierarchical_index": hierarchical_index,
                "collections": collections,
                "statistics": stats,
                "config": asdict(self.config)
            }
            
        except Exception as e:
            print(f"[ERROR] Indexing pipeline failed: {str(e)}")
            return {
                "error": str(e),
                "hierarchical_index": {},
                "collections": {},
                "statistics": {"error": "pipeline_failed"},
                "config": asdict(self.config)
            }
    
    def _generate_index_statistics(self, hierarchical_index: Dict[str, Any], 
                                 collections: Dict[str, Any]) -> Dict[str, Any]:
        """Generate comprehensive index statistics"""
        
        try:
            all_pages = {**hierarchical_index.get("main_pages", {}), 
                        **hierarchical_index.get("sub_pages", {})}
            
            if not all_pages:
                return {
                    "total_pages": 0,
                    "main_pages": 0,
                    "sub_pages": 0,
                    "categories": 0,
                    "collections_created": len(collections),
                    "error": "no_pages_indexed"
                }
            
            stats = {
                "total_pages": len(all_pages),
                "main_pages": len(hierarchical_index.get("main_pages", {})),
                "sub_pages": len(hierarchical_index.get("sub_pages", {})),
                "categories": len(hierarchical_index.get("categories", {})),
                "collections_created": len(collections),
                "embedding_dimensions": 1536,  # text-embedding-3-small
                "index_completion_time": datetime.now().isoformat()
            }
            
            # Calculate average complexity score
            complexity_scores = []
            function_counts = []
            
            for page in all_pages.values():
                try:
                    complexity = page['content']['metadata'].get('complexity_score', 0)
                    if isinstance(complexity, (int, float)):
                        complexity_scores.append(complexity)
                    
                    func_count = page['content']['metadata'].get('function_count', 0)
                    if isinstance(func_count, int):
                        function_counts.append(func_count)
                except (KeyError, TypeError):
                    continue
            
            if complexity_scores:
                stats["average_complexity_score"] = round(sum(complexity_scores) / len(complexity_scores), 2)
            else:
                stats["average_complexity_score"] = 0.0
                
            if function_counts:
                stats["total_functions"] = sum(function_counts)
            else:
                stats["total_functions"] = 0
            
            return stats
            
        except Exception as e:
            return {
                "error": f"statistics_generation_failed: {str(e)}",
                "total_pages": 0,
                "collections_created": len(collections),
                "index_completion_time": datetime.now().isoformat()
            }

def main():
    """Main function to run the indexing pipeline"""
    
    # Configuration
    config = IndexingConfig(
        source_json="data/forza_map.json",
        output_dir="data/vector_index",
        embedding_model="text-embedding-3-small",
        enable_hierarchy=True,
        enable_context_enrichment=True,
        enable_semantic_categorization=True
    )
    
    # Create output directory
    os.makedirs(config.output_dir, exist_ok=True)
    
    # Run indexing pipeline
    orchestrator = IndexingOrchestrator(config)
    result = orchestrator.run_full_indexing_pipeline()
    
    # Save index metadata
    try:
        output_path = Path(config.output_dir) / "index_metadata.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            # Remove non-serializable objects
            serializable_result = {
                "statistics": result["statistics"],
                "config": result["config"],
                "completion_timestamp": datetime.now().isoformat(),
                "success": "error" not in result
            }
            json.dump(serializable_result, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Index metadata saved to: {output_path}")
    except Exception as e:
        print(f"[WARNING]  Error saving metadata: {str(e)}")
    
    if "error" not in result:
        print("\n🔍 Your advanced ERP navigation index is ready!")
        print("   • Multi-level semantic search enabled")
        print("   • Context-aware retrieval optimized") 
        print("   • Hierarchical relationships preserved")
        print("   • User intent understanding active")
        print("   • ChromaDB metadata compatibility ensured")
    else:
        print(f"\n[ERROR] Indexing completed with errors: {result['error']}")

if __name__ == "__main__":
    main()