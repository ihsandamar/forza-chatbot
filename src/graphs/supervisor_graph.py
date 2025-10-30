from langgraph_supervisor import create_supervisor

from src.graphs.chat_graph import ChatGraph
from src.graphs.registry import register_graph
from src.graphs.text2sql_graph import Text2SQLGraph
from src.tools.forza_api_tools import ForzaAPIToolkit
from langchain_core.tools import tool
from datetime import datetime  
from src.graphs.base_graph import BaseGraph

from langgraph.graph import StateGraph, START, END
from src.graphs.base_graph import BaseGraph
from src.models.models import LLM, State
from langgraph.checkpoint.memory import MemorySaver
@tool
def get_today() -> str:
    "Return today"
    return datetime.today().strftime('%Y-%m-%d')

@tool
def get_introduction() -> str:
    """Provide a friendly introduction when user greets or asks about the system"""
    return """
[WAVE] **Merhaba! Ben Akıllı Müşteri Hizmetleri,**

🎯 **Size Nasıl Yardımcı Olabilirim:**
• Uzman modüllerimi kullanarak sorularınızı en uygun uzmana yönlendiririm
• Farklı konularda detaylı bilgi ve destek sağlarım
• İşletmenizin ihtiyaçlarına göre özelleştirilmiş çözümler sunarım

🔧 **Mevcut Uzman Modüllerim:**
• Master Raporlama Sistemi
• Forza ERP Entegrasyonu  
• ŞEFIM Master Panel Kullanımı
• Özel SQL Sorgu Sistemi
• Türk Vergi Mevzuatı
• Genel Müşteri Desteği

💡 **Başlamak için:** "Hangi modüller var?" diyebilir veya doğrudan sorunuzu sorabilirsiniz. Ben sizin için en uygun uzmanı bulacağım!

[ROCKET] **Hemen başlayalım - size nasıl yardımcı olabilirim?**
    """

@tool
def list_modules() -> str:
    """List all available specialist modules in the supervisor system"""
    return """
🔧 **Available Specialist Modules**

📋 **Uzman Modüller:**
• master_report - Master Raporlama Sistemi
• forza_erp - Forza ERP Entegrasyonu
• sefim_master_panel - ŞEFIM Master Panel Kullanımı
• text2sql - Özel SQL Sorgu Sistemi
• mevzuat - Türk Vergi Mevzuatı
• genel_chat - Genel Müşteri Desteği

🛠️ **Direct Tools:**
• get_today - Current date utility
• login - Forza ERP authentication
• get_businesses_by_user_id - User business retrieval
• get_branches_by_business_id - Branch management
• get_user_branches - Complete ERP workflow

💡 **Usage:** Use get_module_info('module_name') for detailed information about any module.
    """

@tool
def get_module_info(module_name: str) -> str:
    """Get detailed information about a specific module including capabilities and example questions"""
    
    modules = {
        "master_report": {
            "name": "Master Raporlama Sistemi",
            "purpose": "Kapsamlı raporlama ve doküman işlemleri için özelleştirilmiş sistem",
            "capabilities": [
                "Master rapor üretimi ve analizi",
                "Doküman arama ve yönetimi",
                "Dosya işlemleri ve içerik analizi",
                "Standart raporlama sistemleri",
                "İçerik analizi ve çıkarımı"
            ],
            "example_questions": [
                "Master satış raporu oluştur",
                "Belirli anahtar kelimeleri içeren dokümanları bul",
                "Kapsamlı iş raporu oluştur",
                "Belirli dosyaları bul ve getir",
                "Master raporlama özelliklerine ihtiyacım var"
            ]
        },
        "forza_erp": {
            "name": "Forza ERP Entegrasyonu",
            "purpose": "Forza ERP sistemi ile doğrudan API entegrasyonu ve işlemler",
            "capabilities": [
                "Kullanıcı kimlik doğrulama ve giriş",
                "İşletme ve şube yönetimi",
                "Doğrudan ERP API işlemleri",
                "Gerçek zamanlı ERP veri erişimi",
                "Sistem entegrasyon görevleri"
            ],
            "example_questions": [
                "ERP hesabıma giriş yap",
                "İşletmelerimi ve şubelerimi göster",
                "Doğrudan ERP işlemleri gerçekleştir",
                "Gerçek zamanlı ERP verilerine eriş",
                "ERP kullanıcı hesaplarını yönet"
            ]
        },
        "sefim_master_panel": {
            "name": "ŞEFIM Master Panel Kullanımı",
            "purpose": "ŞEFIM sistemine özel sorular ve dokümantasyon desteği",
            "capabilities": [
                "ŞEFIM dokümantasyon arama ve erişimi",
                "ŞEFIM süreç açıklamaları",
                "ŞEFIM özel sorun giderme",
                "ŞEFIM uyumluluk rehberliği",
                "ŞEFIM sistem bilgisi"
            ],
            "example_questions": [
                "ŞEFIM ayarlarını nasıl yapılandırabilirim?",
                "ŞEFIM onay süreci nasıl işler?",
                "ŞEFIM uyumluluk gereksinimlerini açıkla",
                "X özelliği hakkında ŞEFIM dokümantasyonu bul",
                "ŞEFIM sistem sorunları ile yardım et"
            ]
        },
        "text2sql": {
            "name": "Özel SQL Sorgu Sistemi",
            "purpose": "Karmaşık veritabanı işlemleri ve özel SQL istekleri için uzman sistem",
            "capabilities": [
                "Özel SQL sorgu üretimi ve çalıştırma",
                "Karmaşık veritabanı işlemleri",
                "Gelişmiş veri analizi ve filtreleme",
                "Özel kriterlerle raporlama",
                "Veritabanı şema keşfi"
            ],
            "example_questions": [
                "Son 6 ayda X ürününü satın alan tüm müşterileri bulan özel SQL sorgusu yaz",
                "Birden fazla tabloyu birleştiren karmaşık rapor oluştur",
                "Gelişmiş veri analizi için SQL üret",
                "Özel veritabanı sorgusu yazmama yardım et",
                "Karmaşık SQL işlemlerine ihtiyacım var"
            ]
        },
        "mevzuat": {
            "name": "Türk Vergi Mevzuatı",
            "purpose": "Türk vergi hukuku ve GIB düzenlemeleri konusunda uzman sistem",
            "capabilities": [
                "Türk vergi hukuku rehberliği",
                "GIB düzenleme arama ve açıklama",
                "Vergi uyumluluk yardımı",
                "Mevzuat doküman erişimi",
                "Vergi ile ilgili yasal rehberlik"
            ],
            "example_questions": [
                "Güncel KDV düzenlemeleri neler?",
                "Türk kurumlar vergisi gereksinimlerini açıkla",
                "X konusu hakkında GIB mevzuatı bul",
                "Vergi uyumluluk sorunları ile yardım et",
                "Türk vergi hukuku soruları"
            ]
        },
        "genel_chat": {
            "name": "Genel Müşteri Desteği",
            "purpose": "Genel konuşmalar, sorular, açıklamalar ve müşteri yardımı",
            "capabilities": [
                "Genel müşteri desteği ve konuşmalar",
                "Ürün bilgileri ve özellikler",
                "Hesap yardımı ve sorun giderme",
                "Teknik destek ve rehberlik",
                "Süreç açıklamaları ve nasıl yapılır yardımı",
                "Özellik açıklamaları ve eğitimler"
            ],
            "example_questions": [
                "Sipariş süreci nasıl işler?",
                "X ürününün özellikleri neler?",
                "Hesap kurulumu ile yardım edebilir misin?",
                "Bu özelliği nasıl kullanacağımı açıkla",
                "Genel müşteri desteğine ihtiyacım var"
            ]
        }
    }
    
    if module_name not in modules:
        available_modules = ", ".join(modules.keys())
        return f"[ERROR] Module '{module_name}' not found. Available modules: {available_modules}"
    
    module = modules[module_name]
    
    return f"""
🔍 **{module['name']} ({module_name})**

📋 **Purpose:**
{module['purpose']}

[FLASH] **Capabilities:**
{chr(10).join(f"• {cap}" for cap in module['capabilities'])}

💡 **Example Questions You Can Ask:**
{chr(10).join(f"[OK] \"{q}\"" for q in module['example_questions'])}

🎯 **How to Use:**
Simply ask your question naturally, and the supervisor will route you to this specialist automatically based on your request content.
    """



@register_graph("supervisor")
class SupervisorTestGraph(BaseGraph):
    def __init__(self, llm: LLM):
        super().__init__(llm, State)





    def build_graph(self):
        from src.graphs.graph_entrypoints import (
            text2sql_graph,
            sefim_rag, forza_rag, gib_mevzuat, forza_toolkit,
            generic_sql_payment_graph,
            query_extraction,
        )
        
        # Initialize all specialized graphs
        chat_graph = ChatGraph(self.llm).build_graph()
        text2sql_graph_agent = text2sql_graph()
        generic_document_agent = query_extraction()
        sefim_rag_agent = sefim_rag()
        forza_rag_agent = forza_rag()
        gib_mevzuat_agent = gib_mevzuat()
        forza_toolkit_agent = forza_toolkit()
        
        # Initialize Forza API Toolkit for direct tool access
        forza_toolkit = ForzaAPIToolkit(base_url="http://localhost:8080")
        forza_tools = forza_toolkit.get_tools()
        
        # Agent'lara name attribute'u ekle
        chat_graph.name = "chat_graph"
        text2sql_graph_agent.name = "text2sql_graph"
        generic_document_agent.name = "generic_document_agent"
        sefim_rag_agent.name = "sefim_rag_agent"
        forza_rag_agent.name = "forza_rag_agent"
        gib_mevzuat_agent.name = "gib_mevzuat_agent"
        forza_toolkit_agent.name = "forza_toolkit_agent"
        
        supervisor = create_supervisor(
            model=self.llm.get_chat(), 
            agents=[
                chat_graph, 
                text2sql_graph_agent,
                generic_document_agent,
                sefim_rag_agent,
                forza_rag_agent, 
                gib_mevzuat_agent,
                forza_toolkit_agent
            ],
            tools=[get_today, get_introduction, list_modules, get_module_info] + forza_tools,
            output_mode="full_history",  # Ensure we get complete agent responses
            prompt=(
                "You are an intelligent customer service supervisor managing specialized support agents. "
                "Your role is to analyze customer requests and direct them to the most appropriate expert. "
                "\n"
                "Available specialists:\n"
                "- chat_graph: General customer support specialist for conversations, questions, explanations, and assistance\n"
                "- text2sql_graph: Custom SQL query specialist for complex database operations and custom SQL requests\n"
                "- generic_document_agent: Master report specialist for document search, reporting, file operations, and content retrieval\n"
                "- generic_payment_agent: Master payment report specialist for payment analysis, transaction reports, and financial data\n"
                "- sefim_rag_agent: SEFIM knowledge base specialist for SEFIM-related questions and documentation\n"
                "- forza_rag_agent: Forza ERP knowledge base specialist for ERP documentation and guides\n"
                "- gib_mevzuat_agent: Turkish tax law and regulation specialist for GIB mevzuat queries\n"
                "- forza_toolkit_agent: Forza ERP API specialist for direct ERP operations (login, branches, businesses)\n"
                "\n"
                "Decision criteria:\n"
                "- Use chat_graph for: General conversations, product information, troubleshooting, explanations\n"
                "- Use text2sql_graph for: Custom SQL requests, complex database operations, advanced data analysis\n"
                "- Use generic_document_agent for: Master reports, amount reports, ciro ve satış raporları\n"
                "- Use sefim_rag_agent for: SEFIM-specific questions, SEFIM documentation, SEFIM processes\n"
                "- Use forza_rag_agent for: Forza ERP documentation, ERP guides, system explanations\n"
                "- Use gib_mevzuat_agent for: Turkish tax law questions, GIB regulations, tax compliance, mevzuat search\n"
                "- Use forza_toolkit_agent for: Direct ERP operations, user login, branch management, business data\n"
                "\n"
                "Always provide helpful, professional customer service. Be proactive in understanding customer needs.\n"
                "\n"
                "Available tools:\n"
                "- get_introduction: Use when customer greets, says hello, or asks who you are\n"
                "- list_modules: Use when customer asks about available modules, services, capabilities, or 'what can you help with?'\n"
                "- get_module_info: Use when customer wants detailed information about a specific module (provide module_name)\n"
                "- get_today: Use when current date is needed\n"
                "- login: Forza ERP user authentication\n"
                "- get_businesses_by_user_id: Get businesses for a specific user\n"
                "- get_branches_by_business_id: Get branches for a specific business\n"
                "- get_user_branches: Complete ERP workflow - login, get businesses, then get all branches\n"
                "\n"
                "Priority routing:\n"
                "1. For tax/regulation questions → gib_mevzuat_agent\n"
                "2. For master report requests → generic_document_agent\n"
                "3. For master payment reports → generic_payment_agent\n"
                "4. For custom SQL requests → text2sql_graph\n"
                "5. For ERP operations → forza_toolkit_agent\n"
                "6. For SEFIM questions → sefim_rag_agent\n"
                "7. For Forza questions → forza_rag_agent\n"
                "8. For general queries → chat_graph\n"
            )
        )
        memory = MemorySaver()
        return supervisor.compile(checkpointer=memory)                