"""
Dynamic business terms configuration for semantic matching
"""
from typing import Dict, List, Any
import json
import os

class BusinessTermsConfig:
    def __init__(self, config_path: str = None):
        """Initialize business terms configuration
        
        Args:
            config_path: Path to configuration file. If None, uses default config.
        """
        if config_path is None:
            # Use default path relative to project root
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(current_dir))
            config_path = os.path.join(project_root, "config", "business_terms.json")
        
        self.config_path = config_path
        self._config_data = None
        self.load_config()
    
    def load_config(self):
        """Load configuration from file or use defaults"""
        if self.config_path and os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self._config_data = json.load(f)
            except Exception as e:
                print(f"Error loading config from {self.config_path}: {e}")
                self._config_data = self._get_default_config()
        else:
            self._config_data = self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration"""
        return {
            "business_mappings": {
                "dogalgaz": ["dogalgaz", "doğalgaz", "dogalgz", "gaz", "natural gas"],
                "elektrik": ["elektrik", "electric", "enerji", "energy"],
                "su": ["su", "water"],
                "bank": ["bank", "banka"],
                "market": ["market", "pazar", "mağaza"],
                "telecom": ["telecom", "telekom", "iletişim"],
                "firma": ["şirket", "firma", "limited", "anonim", "company"],
                "store": ["store", "mağaza", "dükkan"]
            },
            "common_terms": [
                "doğalgaz", "elektrik", "su", "gaz", "enerji", 
                "telecom", "bank", "market", "store", 
                "şirket", "firma", "limited", "anonim"
            ],
            "semantic_similarity_threshold": 0.7,
            "max_distinct_values": 100
        }
    
    def get_business_mappings(self) -> Dict[str, List[str]]:
        """Get business term mappings"""
        return self._config_data.get("business_mappings", {})
    
    def get_common_terms(self) -> List[str]:
        """Get common business terms"""
        return self._config_data.get("common_terms", [])
    
    def get_semantic_threshold(self) -> float:
        """Get semantic similarity threshold"""
        return self._config_data.get("semantic_similarity_threshold", 0.7)
    
    def get_max_distinct_values(self) -> int:
        """Get maximum distinct values to process"""
        return self._config_data.get("max_distinct_values", 100)
    
    def add_business_term(self, category: str, terms: List[str]):
        """Add new business term category"""
        if "business_mappings" not in self._config_data:
            self._config_data["business_mappings"] = {}
        
        self._config_data["business_mappings"][category] = terms
        
        # Update common terms
        if "common_terms" not in self._config_data:
            self._config_data["common_terms"] = []
        
        for term in terms:
            if term not in self._config_data["common_terms"]:
                self._config_data["common_terms"].append(term)
    
    def remove_business_term(self, category: str):
        """Remove business term category"""
        if "business_mappings" in self._config_data:
            self._config_data["business_mappings"].pop(category, None)
    
    def save_config(self, save_path: str = None):
        """Save current configuration to file"""
        path = save_path or self.config_path
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(self._config_data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Error saving config to {path}: {e}")
    
    def reload_config(self):
        """Reload configuration from file"""
        self.load_config()

# Global instance
business_config = BusinessTermsConfig()