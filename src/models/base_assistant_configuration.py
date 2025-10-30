# src/models/base_assistant_configuration.py
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from src.services.app_logger import log


class BaseAssistantConfiguration(BaseModel):
    """Base configuration class for all assistant configurations"""
    
    # Core Assistant Settings
    system_prompt: str = Field(
        default="Sen yardımcı bir asistansın.",
        description="Ana sistem promptu - assistant'ın rolünü ve davranışını belirler"
    )
    
    assistant_name: str = Field(
        default="Assistant",
        description="Assistant'ın adı"
    )
    
    @classmethod
    def create_from_config(cls, config_dict: Optional[Dict[str, Any]] = None):
        """
        Configuration dict'ten configuration oluşturur.
        Eğer config gelmezse default değerler kullanılır ve log atılır.
        """
        if config_dict is None:
            print(f"WARNING: {cls.__name__} için config verilmedi, default değerler kullanılıyor")
            return cls()
        
        try:
            # Eğer config_dict bir Config objesi ise dict'e çevir
            if hasattr(config_dict, '__dict__'):
                config_dict = config_dict.__dict__
            elif hasattr(config_dict, 'dict'):
                config_dict = config_dict.dict()
            
            # Config dict'ten instance oluştur
            return cls(**config_dict)
        except Exception as e:
            print(f"WARNING: {cls.__name__} oluşturulurken hata: {e}. Default değerler kullanılıyor")
            return cls()
    
    def to_dict(self) -> Dict[str, Any]:
        """Configuration'ı dict'e çevirir"""
        return self.model_dump()