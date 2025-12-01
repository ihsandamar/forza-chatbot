# src/graphs/forza_routing_graph.py

import os
import json
from dotenv import load_dotenv
from langgraph.graph import StateGraph
from abc import ABC, abstractmethod

from src.tools.forza_routing_toolkit import ForzaRoutingToolkit

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_core.messages import AIMessage
import chromadb
from chromadb.config import Settings
from typing import Tuple, TypedDict, Optional, Dict, Any, List
from src.graphs.base_graph import BaseGraph
from src.graphs.registry import register_graph
from src.models.llm import LLM
from src.services.config_loader import ConfigLoader
from langgraph.graph.message import add_messages, AnyMessage
from langchain_core.documents import Document
from typing_extensions import List, TypedDict
import json
import traceback
from typing import Any, Dict, Optional
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, BaseMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph import MessagesState

config = ConfigLoader.load_config("config/config.yaml")
load_dotenv()


# ============================================================================
# URL BUILDER UTILITY
# ============================================================================

def build_forza_url(url_template: str) -> str:
    """
    Build the complete Forza URL by replacing {baseUrl} placeholder with web_site_url from config.

    Args:
        url_template: URL template that may contain {baseUrl} placeholder

    Returns:
        Complete URL with baseUrl replaced by web_site_url from config
    """
    web_site_url = config.forza.web_site_url
    return url_template.replace("{baseUrl}", web_site_url)


class NavigationState(MessagesState):

    user_input: str
    related_pages: List[tuple]  # List of (Document, score) tuples
    most_related_document: Optional[Document]
    has_parameters: bool
    filled_parameters: Optional[Dict[str, Dict[str, Any]]]  # Updated format: param_name -> {parameter_name, value, display_name}
    tool_results: Optional[List[Dict[str, Any]]]
    tool_results_valid: Optional[bool]
    tried_page_ids: Optional[set]
    retry_count: Optional[int]
    no_more_alternatives: Optional[bool]
    token: str
    navigation_output: Optional[Dict[str, Any]] = None


class NavigationParameter(TypedDict):
    name: str
    type: str  # "guid", "integer", "string"
    description: str
    required: bool
    default: Optional[Any]


class NavigationOutput(TypedDict):
    # Temel sayfa bilgileri
    page_id: str
    page_title: str
    url: str
    category: str
    
    # Sub-page bilgileri
    is_sub_page: bool
    sub_page_type: Optional[str]  # "tab", "link", None
    parent_page_id: Optional[str]
    parent_page_title: Optional[str]
    full_path: Optional[str]  # "Master Raporları > Ciro Raporu"
    
    # Parametreli linkler için
    requires_parameters: bool
    parameters: Optional[Dict[str, NavigationParameter]]
    
    # RAG confidence ve açıklama
    confidence: float
    reasoning: str  # "Müşteri bilgileri yönetimi için en uygun sayfa"
    
    # Frontend için display bilgileri
    suggestion_text: str  # "Bu sayfada ciro raporlarını görebilirsiniz"
    cta_text: str  # "Sayfaya Git" veya "Parametreleri Girin"
    
    # Alternatif öneriler
    alternative_suggestions: Optional[List[Dict[str, Any]]]


# ============================================================================
# BASE NODE ARCHITECTURE
# ============================================================================

class BaseNode(ABC):
    """Abstract base class for all navigation graph nodes"""
    
    def __init__(self, llm: Optional[LLM] = None, vectorstore: Chroma = None):
        self.llm = llm
        self.vectorstore = vectorstore
    
    @abstractmethod
    def invoke(self, state: NavigationState) -> NavigationState:
        """Process the state and return updated state"""
        pass



# ============================================================================
# NODE IMPLEMENTATIONS
# ============================================================================

class DocumentRetrievalNode(BaseNode):
    """Retrieves relevant documents based on user input"""
    
    def invoke(self, state: NavigationState) -> NavigationState:
        """Find documents similar to user input"""
        if not self.vectorstore:
            print("[ERROR] Vectorstore not available for document retrieval")
            state["related_pages"] = []
            return state

        try:
            user_input = state["user_input"]

            # Use similarity_search instead of similarity_search_with_relevance_scores
            # to avoid distance metric normalization issues
            retrieved_docs = self.vectorstore.similarity_search(
                user_input,
                k=5  # Return top 5 results
            )

            # Assign default scores (1.0 for first, decreasing for others)
            # This is a workaround since we can't get actual relevance scores
            docs_with_scores = [
                (doc, 1.0 - (i * 0.1))  # Score: 1.0, 0.9, 0.8, 0.7, 0.6
                for i, doc in enumerate(retrieved_docs)
            ]

            state["related_pages"] = docs_with_scores
            print(f"[DEBUG] Found {len(retrieved_docs)} related documents")

        except KeyError as e:
            print(f"[ERROR] KeyError in document retrieval: Missing key {e}")
            print(f"[ERROR] Available state keys: {list(state.keys())}")
            state["related_pages"] = []
        except Exception as e:
            print(f"[ERROR] Document retrieval failed: {e}")
            state["related_pages"] = []

        return state


class MostRelatedPageNode(BaseNode):
    """Selects the most relevant document from retrieved results"""
    
    def invoke(self, state: NavigationState) -> NavigationState:
        """Select the highest scoring document"""
        if not state["related_pages"]:
            print("[WARNING] No related pages found")
            state["most_related_document"] = None
            return state

        # Get the first (highest score) document
        most_related_document, score = state["related_pages"][0]
        state["most_related_document"] = most_related_document
        
        print(f"[DEBUG] Selected document: {most_related_document.metadata.get('title', 'Unknown')} (score: {score:.3f})")
        return state


class ParameterCheckNode(BaseNode):
    """Checks if the selected document requires URL parameters"""

    def invoke(self, state: NavigationState) -> NavigationState:
        """Determine if document has URL parameters"""
        if not state["most_related_document"]:
            state["has_parameters"] = False
            return state

        metadata = state["most_related_document"].metadata
        url_parameters = self._parse_url_parameters(metadata.get("url_parameters", {}))

        has_params = bool(url_parameters and len(url_parameters) > 0)
        state["has_parameters"] = has_params

        print(f"[DEBUG] Document has parameters: {has_params}")
        return state

    def _parse_url_parameters(self, url_parameters: Any) -> Optional[Dict[str, Any]]:
        """Parse string or dict format url_parameters"""
        if isinstance(url_parameters, str):
            try:
                return json.loads(url_parameters)
            except json.JSONDecodeError:
                print(f"[ERROR] Invalid JSON in url_parameters: {url_parameters}")
                return None
        return url_parameters or {}




class ParameterFillingNode(BaseNode):
    """Fills URL parameters using appropriate tools"""
    
    def invoke(self, state: NavigationState) -> NavigationState:
        """Execute tools to gather parameter values"""
        if not state.get("has_parameters") or not state.get("most_related_document"):
            return state

        token = state.get("token")
        if not token:
            print("[WARNING] No token available for toolkit")
            return state

        metadata = state["most_related_document"].metadata
        page_title = metadata.get("title", "")
        url_parameters = self._parse_url_parameters(metadata.get("url_parameters"))

        if not url_parameters:
            return state

        toolkit = ForzaRoutingToolkit(
            base_url=config.forza.base_url,
            token=token
        )

        try:
            filled_params = self._execute_tools_for_parameters(
                state, page_title, url_parameters, toolkit
            )
            if filled_params:
                state["filled_parameters"] = filled_params
        except Exception as e:
            print(f"[ERROR] Parameter filling failed: {e}")

        return state
    
    def _parse_url_parameters(self, url_parameters: Any) -> Optional[Dict[str, Any]]:
        """Parse URL parameters from metadata"""
        if isinstance(url_parameters, str):
            try:
                return json.loads(url_parameters)
            except json.JSONDecodeError:
                return None
        return url_parameters or {}

    def _check_tool_results_validity(self, messages: List) -> bool:
        """Check if any tool returned valid results with data"""
        for msg in messages:
            if not isinstance(msg, ToolMessage):
                continue

            try:
                result = json.loads(msg.content)

                # Check for error status
                if result.get("status") == "error":
                    continue

                # Check for valid data
                data = result.get("data", {})

                # Tool'lar farklı key'ler kullanabilir (items, customers, products, vb.)
                # Herhangi bir liste alanını ara
                found_valid_data = False
                for key, value in data.items():
                    if isinstance(value, list) and len(value) > 0:
                        print(f"[DEBUG] Found valid tool result with {len(value)} {key}")
                        found_valid_data = True
                        break

                # totalCount kontrolü (opsiyonel)
                total_count = data.get("totalCount", 0)
                if found_valid_data and total_count > 0:
                    return True
                elif found_valid_data:
                    # totalCount yoksa ama liste varsa yine de geçerli say
                    return True

            except (json.JSONDecodeError, AttributeError, KeyError) as e:
                print(f"[WARNING] Could not parse tool message: {e}")
                continue

        print("[WARNING] No valid tool results found in messages")
        return False

    def _execute_tools_for_parameters(self, state: NavigationState, page_title: str,
                                    url_parameters: Dict[str, Any], toolkit: ForzaRoutingToolkit) -> Dict[str, Any]:
        """Execute tools and let LLM parse results to filled_parameters format"""
        tools = toolkit.get_tools()

        try:
            llm_with_tools = self.llm.get_chat().bind_tools(tools)
            prompt = self._build_tool_execution_prompt(state["user_input"], page_title, url_parameters)

            print("[DEBUG] Step 1: Sending prompt to LLM for tool selection...")
            messages = [HumanMessage(content=prompt)]
            response = llm_with_tools.invoke(messages)

            if not response.tool_calls:
                print("[WARNING] LLM did not make any tool calls")
                return {}

            print(f"[DEBUG] Step 2: Executing {len(response.tool_calls)} tool(s)...")
            messages.append(response)

            # Execute all tools and append results
            for tool_call in response.tool_calls:
                # Handle both dict and object formats
                if isinstance(tool_call, dict):
                    tool_name = tool_call.get('name')
                    tool_args = tool_call.get('args', {})
                    tool_id = tool_call.get('id')
                else:
                    tool_name = getattr(tool_call, 'name', None)
                    tool_args = getattr(tool_call, 'args', {})
                    tool_id = getattr(tool_call, 'id', None)

                selected_tool = next((t for t in tools if t.name == tool_name), None)
                if not selected_tool:
                    print(f"[WARNING] Tool '{tool_name}' not found")
                    continue

                try:
                    result = selected_tool.invoke(tool_args)
                    print(f"[DEBUG] Tool '{tool_name}' executed successfully")
                    print(f"[DEBUG] Tool result: {json.dumps(result, ensure_ascii=False)[:200]}...")

                    messages.append(ToolMessage(
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=tool_id
                    ))
                except Exception as tool_error:
                    print(f"[ERROR] Tool '{tool_name}' execution failed: {tool_error}")
                    messages.append(ToolMessage(
                        content=json.dumps({"status": "error", "error": str(tool_error)}, ensure_ascii=False),
                        tool_call_id=tool_id
                    ))

            # Step 3: Check if tools returned valid results
            print("[DEBUG] Step 3: Checking tool results validity...")
            has_valid_results = self._check_tool_results_validity(messages)

            if not has_valid_results:
                print("[WARNING] No valid tool results found, returning empty parameters")
                return {}

            # Step 4: Ask LLM to format results as filled_parameters
            print("[DEBUG] Step 4: Asking LLM to format results as filled_parameters...")
            final_prompt = f"""Kullanıcı isteği: "{state["user_input"]}"

Tool'lardan aldığın sonuçlara göre parametreleri doldur.

Gerekli URL parametreleri: {json.dumps(url_parameters, ensure_ascii=False)}

Tool sonuçlarından KULLANICI İSTEĞİNE EN UYGUN değeri seç ve bu formatta JSON döndür:

{{
  "parametre_ismi": {{
    "parameter_name": "parametre_ismi",
    "value": "id_değeri",
    "display_name": "görünen_isim"
  }}
}}

KRİTİK KURALLAR:
1. EĞER tool sonuçları boş veya hatalıysa, MUTLAKA boş JSON döndür: {{}}
2. EĞER tool'lardan başarılı sonuç gelmediyse (status: error, totalCount: 0, items: []), MUTLAKA boş JSON döndür: {{}}
3. SADECE başarılı tool sonucu varsa ve items listesinde veri varsa parametre doldur
4. Tool sonuçlarından kullanıcı isteğine en uygun olanı seç (ilk değil, EN UYGUN)
5. Sadece düz JSON döndür (markdown yok, açıklama yok)
6. Tool'lar standart format kullanır: {{"data": {{"items": [{{"id": "...", "name": "..."}}, ...], "totalCount": X}}}}

Sadece JSON döndür:"""

            messages.append(HumanMessage(content=final_prompt))
            final_response = self.llm.get_chat().invoke(messages)

            # Parse JSON from response
            import re
            response_text = final_response.content if hasattr(final_response, 'content') else str(final_response)
            print(f"[DEBUG] LLM final response (first 300 chars): {response_text[:300]}")

            # Try multiple JSON extraction strategies
            filled_parameters = None

            # Strategy 1: Try to find JSON in markdown code blocks
            code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if code_block_match:
                try:
                    filled_parameters = json.loads(code_block_match.group(1))
                    print("[DEBUG] Extracted JSON from markdown code block")
                except json.JSONDecodeError:
                    pass

            # Strategy 2: Try to find raw JSON
            if not filled_parameters:
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    try:
                        filled_parameters = json.loads(json_match.group())
                        print("[DEBUG] Extracted JSON from raw text")
                    except json.JSONDecodeError:
                        pass

            # Strategy 3: Try entire response as JSON
            if not filled_parameters:
                try:
                    filled_parameters = json.loads(response_text.strip())
                    print("[DEBUG] Entire response was valid JSON")
                except json.JSONDecodeError:
                    pass

            if filled_parameters:
                print(f"[DEBUG] Successfully parsed filled_parameters: {list(filled_parameters.keys())}")
                print(f"[DEBUG] Filled parameters content: {json.dumps(filled_parameters, ensure_ascii=False)}")
                return filled_parameters
            else:
                print("[WARNING] Could not parse JSON from LLM response")
                print(f"[WARNING] Full response: {response_text}")
                return {}

        except Exception as e:
            print(f"[ERROR] LLM processing error: {e}")
            traceback.print_exc()
            return {}

    def _map_tool_result_to_parameters(self, tool_name: str, result: Dict[str, Any],
                                      url_parameters: Dict[str, Any], filled_parameters: Dict[str, Any]):
        """Dynamically map tool results to URL parameters"""
        if result.get("status") != "success":
            print(f"[WARNING] Tool '{tool_name}' returned non-success status")
            return

        data = result.get("data", {})

        # Find all list-type data in result
        for key, value in data.items():
            if not isinstance(value, list) or not value:
                continue

            # Get first item from list
            first_item = value[0]
            if not isinstance(first_item, dict):
                continue

            # Extract potential parameter name from list key (e.g., "customers" -> "customerId")
            param_candidates = self._generate_parameter_candidates(key)

            # Find matching parameter in url_parameters
            matched_param = None
            for candidate in param_candidates:
                if candidate in url_parameters:
                    matched_param = candidate
                    break

            if not matched_param:
                continue

            # Extract ID and display value from item
            id_value = self._extract_id_value(first_item, matched_param)
            display_value = self._extract_display_value(first_item)

            if id_value:
                filled_parameters[matched_param] = {
                    "parameter_name": matched_param,
                    "value": id_value,
                    "display_name": display_value
                }
                print(f"[DEBUG] Mapped {matched_param}: {id_value} ({display_value})")

    def _generate_parameter_candidates(self, list_key: str) -> List[str]:
        """Generate possible parameter names from list key"""
        # Remove 's' or 'List' suffix and add 'Id'
        base = list_key.rstrip('s').replace('List', '')
        return [
            f"{base}Id",
            f"{base.lower()}id",
            f"{base}ID",
            base,  # sometimes parameter name matches list key exactly
            f"custumer{base[8:]}" if base.startswith("customer") else None,  # handle typo: custumerId
        ]

    def _extract_id_value(self, item: Dict[str, Any], param_name: str) -> Any:
        """Extract ID value from item - try multiple common ID field names"""
        # Try exact match first
        if param_name in item:
            return item[param_name]

        # Try common ID field names
        id_candidates = [
            param_name,
            param_name.replace("Id", "ID"),
            "id",
            "ID",
            f"{param_name[:-2]}Id" if param_name.endswith("Id") else None,
        ]

        for candidate in id_candidates:
            if candidate and candidate in item:
                return item[candidate]

        return None

    def _extract_display_value(self, item: Dict[str, Any]) -> str:
        """Extract display value from item - try common display field names"""
        display_candidates = ["name", "label", "title", "displayName", "display_name"]

        for candidate in display_candidates:
            if candidate in item and item[candidate]:
                return item[candidate]

        return ""

    def _build_tool_execution_prompt(self, user_input: str, page_title: str,
                                   url_parameters: Dict[str, Any]) -> str:
        """Build optimized prompt for tool execution"""
        param_list = ", ".join(url_parameters.keys())
        return f"""Kullanıcı isteği: "{user_input}"
Hedef sayfa: "{page_title}"
Gerekli parametreler: {param_list}

Görev: Kullanıcı girdisinden ilgili bilgiyi çıkar ve uygun tool'ları çağır.

[CRITICAL] KRITIK TALİMAT - MUTLAKA UYULMALI:
Tool'a SADECE en genel/ana terimi TEK KELİME olarak gönder.

YASAKLAR:
- Marka isimleri kullanma (Yemeksepeti, ABC Firma, vb.)
- Sıfatlar ekleme (özel, premium, yeni, vb.)
- Birden fazla kelime kullanma
- Detay/açıklama ekleme

DOĞRU ÖRNEKLER:
[BAD] "yemeksepeti özel dürüm menü" -> [GOOD] "dürüm"
[BAD] "ABC firması satış raporu" -> [GOOD] "satış"
[BAD] "premium çelik boru ürünü" -> [GOOD] "boru"

SADECE en genel terimi kullan. Birden fazla parametre gerekiyorsa, birden fazla tool çağır."""
    
    def _extract_tool_calls(self, response: Any) -> Optional[list]:
        """Extract tool calls from LLM response - EXACT copy from original"""
        if hasattr(response, 'tool_calls'):
            return response.tool_calls
        if hasattr(response, 'additional_kwargs') and 'tool_calls' in response.additional_kwargs:
            return response.additional_kwargs['tool_calls']
        if isinstance(response, dict) and 'tool_calls' in response:
            return response['tool_calls']
        return None
    
    def _parse_tool_call(self, tool_call: Any) -> Tuple[Optional[str], Dict[str, Any]]:
        """Parse tool call to extract name and arguments - EXACT copy from original"""
        tool_name, tool_args = None, {}
        if isinstance(tool_call, dict):
            tool_name = tool_call.get("function", {}).get("name") or tool_call.get("name")
            args_str = tool_call.get("function", {}).get("arguments") or tool_call.get("args", "{}")
            try:
                tool_args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except:
                tool_args = {}
        else:
            tool_name = getattr(tool_call, "name", None)
            tool_args = getattr(tool_call, "args", {})
        return tool_name, tool_args


class URLUpdateNode(BaseNode):
    """Updates document URL with filled parameter values and baseUrl"""

    def invoke(self, state: NavigationState) -> NavigationState:
        """Replace URL placeholders with actual parameter values and baseUrl"""
        if not state.get("most_related_document"):
            return state

        document = state["most_related_document"]
        metadata = document.metadata

        # URL'i al
        original_url = metadata.get("url_route", "")
        updated_url = original_url

        try:
            # Step 1: Parametreleri doldur (eğer varsa)
            filled_params = state.get("filled_parameters", {})
            if filled_params and state.get("has_parameters"):
                for param_name, param_data in filled_params.items():
                    # Sadece parametre formatındaki verileri işle
                    if isinstance(param_data, dict) and "parameter_name" in param_data and "value" in param_data:
                        parameter_name = param_data["parameter_name"]
                        value = param_data["value"]

                        # URL'deki placeholder'ı bul ve değiştir
                        placeholder = f"{{{parameter_name}}}"

                        if placeholder in updated_url and value:
                            updated_url = updated_url.replace(placeholder, str(value))
                            print(f"[DEBUG] Updated {parameter_name}: {placeholder} -> {value}")

            # Step 2: {baseUrl} placeholder'ını web_site_url ile değiştir (DAIMA yapılmalı)
            updated_url = build_forza_url(updated_url)
            print(f"[DEBUG] Applied baseUrl: {updated_url}")

            # URL güncellenmişse document'ı güncelle
            if updated_url != original_url:
                # Document metadata'sını güncelle
                updated_metadata = metadata.copy()
                updated_metadata["url_route"] = updated_url
                updated_metadata["url_updated"] = True
                updated_metadata["original_url"] = original_url

                # Document objesini güncelle
                updated_document = Document(
                    page_content=document.page_content,
                    metadata=updated_metadata
                )

                state["most_related_document"] = updated_document
                print(f"[OK] URL updated: {original_url} -> {updated_url}")

        except Exception as e:
            print(f"[ERROR] URL update failed: {e}")

        return state


class StateToOutputTransformerNode(BaseNode):
    """Transforms navigation state to final output format"""

    def invoke(self, state: NavigationState) -> NavigationState:
        """Convert navigation state to structured output and add URL as tool message"""
        if not state.get("most_related_document"):
            output = self._create_empty_output()
        else:
            output = self._document_to_navigation_output(state["most_related_document"])

        # Store output in state for supervisor to access
        state["navigation_output"] = output

        # Add URL as proper tool message pair (AIMessage + ToolMessage)
        if output.get("url"):
            url = output["url"]

            # Create AIMessage with tool_calls that will be followed by ToolMessage
            ai_message = AIMessage(
                content="",
                tool_calls=[{
                    "id": "routing_navigation_url",
                    "name": "navigation",
                    "args": {"url": url}
                }]
            )

            # Create ToolMessage as response to the tool call
            tool_message = ToolMessage(
                content=url,
                tool_call_id="routing_navigation_url"
            )

            # Add both messages to state
            messages = state.get("messages", [])
            if not isinstance(messages, list):
                messages = list(messages) if hasattr(messages, '__iter__') else []

            state["messages"] = messages + [ai_message, tool_message]
            print(f"[DEBUG] Navigation URL added as tool message: {url}")

        return state
    
    def _create_empty_output(self) -> NavigationOutput:
        """Create empty output when no document found"""
        return NavigationOutput(
            page_id="",
            page_title="Sayfa bulunamadı",
            url="",
            category="unknown",
            is_sub_page=False,
            sub_page_type=None,
            parent_page_id=None,
            parent_page_title=None,
            full_path=None,
            requires_parameters=False,
            parameters=None,
            confidence=0.0,
            reasoning="Uygun sayfa bulunamadı",
            suggestion_text="Arama kriterlerinizi değiştirip tekrar deneyiniz",
            cta_text="Tekrar Ara",
            alternative_suggestions=None
        )
    
    def _document_to_navigation_output(self, document: Document) -> NavigationOutput:
        """Convert Document to NavigationOutput"""
        metadata = document.metadata

        # Basic page information
        page_id = metadata.get("page_id", "")
        page_title = metadata.get("title", "Bilinmeyen Sayfa")
        url = metadata.get("url_route", "")
        category = metadata.get("category", "unknown")

        # Sub-page detection
        is_sub_page = metadata.get("document_type") == "sub_page"
        sub_page_type = metadata.get("sub_page_type") if is_sub_page else None
        parent_page_id = metadata.get("parent_page_id") if is_sub_page else None
        parent_page_title = metadata.get("main_page_title") if is_sub_page else None
        full_path = metadata.get("full_path") if is_sub_page else None

        # Parameter processing
        requires_parameters, parameters = self._process_parameters(metadata)

        # Display information
        suggestion_text = self._generate_suggestion_text(page_title, is_sub_page, parent_page_title)
        cta_text = "Parametreleri Girin" if requires_parameters else "Sayfaya Git"
        reasoning = self._generate_reasoning(page_title, is_sub_page, parent_page_title)

        return NavigationOutput(
            page_id=page_id,
            page_title=page_title,
            url=url,
            category=category,
            is_sub_page=is_sub_page,
            sub_page_type=sub_page_type,
            parent_page_id=parent_page_id,
            parent_page_title=parent_page_title,
            full_path=full_path,
            requires_parameters=requires_parameters,
            parameters=parameters,
            confidence=0.85,
            reasoning=reasoning,
            suggestion_text=suggestion_text,
            cta_text=cta_text,
            alternative_suggestions=None
        )
    
    def _process_parameters(self, metadata: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, NavigationParameter]]]:
        """Process URL parameters from metadata"""
        has_url_params = metadata.get("has_url_parameters", "no") == "yes"
        parameters = None

        if has_url_params and metadata.get("url_parameters"):
            try:
                url_params = json.loads(metadata.get("url_parameters", "{}"))
                parameters = {}
                for param_name, param_info in url_params.items():
                    parameters[param_name] = NavigationParameter(
                        name=param_name,
                        type=param_info.get("type", "string"),
                        description=param_info.get("description", ""),
                        required=param_info.get("required", False),
                        default=param_info.get("default")
                    )
            except:
                has_url_params = False

        return has_url_params, parameters
    
    def _generate_suggestion_text(self, page_title: str, is_sub_page: bool, parent_page_title: str) -> str:
        """Generate user-friendly suggestion text"""
        if is_sub_page:
            suggestion = f"Bu alt sayfada {page_title.lower()} ile ilgili işlemlerinizi yapabilirsiniz."
            if parent_page_title:
                suggestion += f" ({parent_page_title} bölümü)"
        else:
            suggestion = f"Bu sayfada {page_title.lower()} ile ilgili işlemlerinizi yapabilirsiniz."
        return suggestion
    
    def _generate_reasoning(self, page_title: str, is_sub_page: bool, parent_page_title: str) -> str:
        """Generate reasoning for page selection"""
        reasoning = f"{page_title} sayfası kullanıcının isteği için en uygun sayfa olarak belirlendi."
        if is_sub_page:
            reasoning += f" Ana sayfa: {parent_page_title}"
        return reasoning
    

class CheckToolResultsNode(BaseNode):
    """Check if parameters were successfully filled"""

    def invoke(self, state: NavigationState) -> NavigationState:
        """Verify if tools returned any results"""
        # If page doesn't have parameters, skip validation
        has_parameters = state.get("has_parameters", False)
        if not has_parameters:
            print("[DEBUG] Page has no parameters, skipping validation")
            state["tool_results_valid"] = True
            return state

        filled_parameters = state.get("filled_parameters", {})

        # If parameters were successfully filled, continue with URL update
        if filled_parameters:
            print(f"[OK] Successfully filled {len(filled_parameters)} parameter(s) - continuing with URL update")
            state["tool_results_valid"] = True
            return state

        # If no filled parameters, search for alternatives
        print("[WARNING] No filled parameters - will search for alternatives")
        state["tool_results_valid"] = False
        return state

    def _parse_url_parameters(self, url_parameters: Any) -> Optional[Dict[str, Any]]:
        """Parse URL parameters from metadata"""
        if isinstance(url_parameters, str):
            try:
                return json.loads(url_parameters)
            except json.JSONDecodeError:
                return None
        return url_parameters or {}


class ExtractUserInputFromMessagesNode(BaseNode):
    """Extracts the last user message from messages state and sets it as user_input"""

    def invoke(self, state: NavigationState) -> NavigationState:
        """Extract last user message from messages"""
        messages = state.get("messages", [])

        if messages:
            # Get the last message
            last_message = messages[-1]

            # Extract content based on message type
            if hasattr(last_message, 'content'):
                user_input = last_message.content
            else:
                user_input = str(last_message)

            state["user_input"] = user_input
            print(f"[DEBUG] Extracted user input from messages: {user_input[:100]}...")
        else:
            print("[WARNING] No messages found in state")

        return state


class FindAlternativePagesNode(BaseNode):
    """Finds alternative pages when tool results fail"""

    MAX_RETRIES = 3  # Maximum number of alternative pages to try

    def invoke(self, state: NavigationState) -> NavigationState:
        """Find next best alternative page from related_pages"""
        # Initialize retry counter
        retry_count = state.get("retry_count", 0)

        # Check if we've exceeded max retries
        if retry_count >= self.MAX_RETRIES:
            print(f"[WARNING] Maximum retry limit ({self.MAX_RETRIES}) reached")
            state["no_more_alternatives"] = True
            state["tool_results_valid"] = True  # Force continue to avoid infinite loop
            return state

        if not self.vectorstore:
            print("[ERROR] Vectorstore not available for alternative search")
            state["no_more_alternatives"] = True
            state["tool_results_valid"] = True  # Force continue
            return state

        related_pages = state.get("related_pages", [])

        if not related_pages:
            print("[WARNING] No alternative pages available")
            state["no_more_alternatives"] = True
            state["tool_results_valid"] = True  # Force continue
            return state

        # Get the current document (that failed)
        current_doc = state.get("most_related_document")
        current_page_id = current_doc.metadata.get("page_id") if current_doc else None

        print(f"[DEBUG] Searching for alternatives (current failed: {current_page_id}, retry: {retry_count + 1}/{self.MAX_RETRIES})")

        # Find the next best alternative that hasn't been tried
        tried_pages = state.get("tried_page_ids", set())
        if current_page_id:
            tried_pages.add(current_page_id)

        # Search through related pages for an untried alternative
        for doc, score in related_pages:
            page_id = doc.metadata.get("page_id")

            # Skip if already tried
            if page_id in tried_pages:
                continue

            # Found an alternative
            print(f"[DEBUG] Found alternative page: {doc.metadata.get('title', 'Unknown')} (score: {score:.3f})")
            state["most_related_document"] = doc
            state["tried_page_ids"] = tried_pages
            state["retry_count"] = retry_count + 1

            # Reset parameters for the new attempt
            state["filled_parameters"] = {}
            state["tool_results_valid"] = None
            state["no_more_alternatives"] = False

            return state

        # No more alternatives found
        print("[WARNING] No more alternative pages available in the list")
        state["tried_page_ids"] = tried_pages
        state["no_more_alternatives"] = True
        state["tool_results_valid"] = True  # Force continue to avoid infinite loop
        return state

# ============================================================================
# MAIN GRAPH CLASS
# ============================================================================

@register_graph("vegaforza_navigation")
class VegaforzaNavigationGraph(BaseGraph):
    """Main navigation graph orchestrating all nodes"""
    
    def __init__(self, llm: LLM):
        super().__init__(llm, NavigationState)
        self.vectorstore = self._setup_vectorstore()
        self._initialize_nodes()
    
    def _setup_vectorstore(self):
        """Initialize vectorstore for document retrieval"""
        try:
            import sys
            from pathlib import Path

            # Get runtime base path (works for both dev and exe)
            is_frozen = getattr(sys, 'frozen', False)
            if is_frozen:
                # Running as compiled executable
                base_path = Path(sys.executable).parent
                print(f"[DEBUG] Running as EXE - base path: {base_path}")
            else:
                # Running as script
                base_path = Path(__file__).parent.parent.parent
                print(f"[DEBUG] Running as script - base path: {base_path}")

            vectorstore_path = base_path / "data" / "vector_index" / "vegaforza_chroma_db"
            print(f"[DEBUG] Looking for vectorstore at: {vectorstore_path}")
            print(f"[DEBUG] Vectorstore exists: {vectorstore_path.exists()}")

            if not vectorstore_path.exists():
                print(f"[ERROR] Vectorstore path not found: {vectorstore_path}")
                print(f"[DEBUG] Current working directory: {Path.cwd()}")
                print(f"[DEBUG] sys.executable: {sys.executable if is_frozen else 'N/A'}")
                print(f"[DEBUG] Base path contents: {list(base_path.iterdir())[:10]}")
                return None

            embeddings = OpenAIEmbeddings(
                model="text-embedding-3-small",
                openai_api_key=config.llm.api_key,
                base_url=config.llm.base_url,
            )

            # Force SegmentAPI instead of Rust (fixes PyInstaller compatibility)
            # Rust bindings are not available in PyInstaller, use pure Python implementation
            chroma_settings = Settings(
                anonymized_telemetry=False,
                allow_reset=True,
                chroma_api_impl="chromadb.api.segment.SegmentAPI"  # Use Python implementation instead of Rust
            )

            chroma_client = chromadb.PersistentClient(
                path=str(vectorstore_path),
                settings=chroma_settings
            )

            collection = chroma_client.get_collection("vegaforza_web_pages")
            if collection.count() == 0:
                print("[WARNING] Navigation collection empty")
                return None

            vectorstore = Chroma(
                client=chroma_client,
                collection_name="vegaforza_web_pages",
                embedding_function=embeddings,
            )

            print(f"[OK] Navigation ready - {collection.count()} pages")
            return vectorstore

        except Exception as e:
            print(f"[ERROR] Navigation setup failed: {e}")
            return None
    
    def _initialize_nodes(self):
        """Initialize all node instances"""
        self.extract_user_input_node = ExtractUserInputFromMessagesNode(self.llm)
        self.document_retrieval_node = DocumentRetrievalNode(self.llm, self.vectorstore)
        self.most_related_page_node = MostRelatedPageNode(self.llm)
        self.parameter_check_node = ParameterCheckNode(self.llm)
        self.parameter_filling_node = ParameterFillingNode(self.llm)
        self.check_tool_results_node = CheckToolResultsNode(self.llm)
        self.url_update_node = URLUpdateNode(self.llm)
        self.state_transformer_node = StateToOutputTransformerNode(self.llm)
        self.find_alternative_pages_node = FindAlternativePagesNode(self.llm, self.vectorstore)
    
    def build_graph(self):
        """Build the navigation graph with all nodes"""
        print("[INIT] VegaForza Navigation Graph starting...")

        graph = StateGraph(state_schema=NavigationState)

        # Add nodes
        graph.add_node("extract_user_input", RunnableLambda(self.extract_user_input_node.invoke))
        graph.add_node("find_documents", RunnableLambda(self.document_retrieval_node.invoke))
        graph.add_node("most_related_page", RunnableLambda(self.most_related_page_node.invoke))
        graph.add_node("check_parameters", RunnableLambda(self.parameter_check_node.invoke))
        graph.add_node("fill_parameters_with_toolkit", RunnableLambda(self.parameter_filling_node.invoke))
        graph.add_node("check_tool_results", RunnableLambda(self.check_tool_results_node.invoke))
        graph.add_node("find_alternative_pages", RunnableLambda(self.find_alternative_pages_node.invoke))
        graph.add_node("update_url_with_parameters", RunnableLambda(self.url_update_node.invoke))
        graph.add_node("transform_state_to_output", RunnableLambda(self.state_transformer_node.invoke))

        # Define flow
        graph.set_entry_point("extract_user_input")
        graph.add_edge("extract_user_input", "find_documents")
        graph.add_edge("find_documents", "most_related_page")
        graph.add_edge("most_related_page", "check_parameters")
        graph.add_edge("check_parameters", "fill_parameters_with_toolkit")
        graph.add_edge("fill_parameters_with_toolkit", "check_tool_results")

        # Conditional edge: if tool results fail -> find alternatives, else -> update URL
        graph.add_conditional_edges(
            "check_tool_results",
            self._should_find_alternatives,
            {
                "find_alternatives": "find_alternative_pages",
                "continue": "update_url_with_parameters"
            }
        )

        # After finding alternatives, go back to check_parameters
        graph.add_edge("find_alternative_pages", "check_parameters")

        graph.add_edge("update_url_with_parameters", "transform_state_to_output")
        graph.set_finish_point("transform_state_to_output")

        return graph.compile()

    def _should_find_alternatives(self, state: NavigationState) -> str:
        """Determine if we need to find alternative pages based on tool results validation"""
        tool_results_valid = state.get("tool_results_valid", False)
        no_more_alternatives = state.get("no_more_alternatives", False)

        # If no more alternatives available, force continue
        if no_more_alternatives:
            print("[DEBUG] No more alternatives available, continuing with current result")
            return "continue"

        if tool_results_valid:
            print("[DEBUG] Tool results are valid, continuing to URL update")
            return "continue"
        else:
            print("[DEBUG] Tool results failed, searching for alternative pages")
            return "find_alternatives"