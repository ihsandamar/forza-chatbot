# Two-Tier Supervisor Architecture

## Konsept

Supervisor'ı iki ayrı role ayırma:

```
┌─────────────────────────────────────────────┐
│         TIER 1: Router Supervisor           │
│  (Sadece routing, agent seçimi, forward)    │
└─────────────────────────────────────────────┘
                    ↓
        ┌───────────┴───────────┐
        ↓                       ↓
┌───────────────┐       ┌───────────────┐
│ Routing Agent │       │  Chat Agent   │
└───────────────┘       └───────────────┘
        ↓                       ↓
┌─────────────────────────────────────────────┐
│      TIER 2: Synthesizer Supervisor         │
│  (Cevap üretme, sentezleme, formatting)     │
└─────────────────────────────────────────────┘
```

## Kaynaklar

### LangGraph Hierarchical Teams
- **Kaynak**: [Hierarchical Agent Teams](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/hierarchical_agent_teams/)
- **Pattern**: `forward_message` tool ile supervisor'ın "telefon" rolünü ortadan kaldırma
- **Performans**: %30-40 hız artışı

### AutoGen Orchestrator-Worker
- **Kaynak**: [AutoGen Orchestrator-Worker Pattern](https://medium.com/oracle-saas-paas/autogen-orchestrator-worker-agents-design-pattern-eef8698459b2)
- **Pattern**: Orchestrator dispatch yapar, workers execute eder
- **Synthesis**: Orchestrator worker'ların sonuçlarını toplar ve final response üretir

### Azure AI Agent Patterns
- **Kaynak**: [AI Agent Orchestration Patterns](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns)
- **Pattern**: Linear vs Adaptive Orchestration
- **Key**: Routing layer ve Response generation layer'ın ayrılması

### Kore.ai Supervisor Pattern
- **Kaynak**: [Supervisor Multi-Agent Orchestration](https://docs.kore.ai/agent-platform/ai-agents/supervisor/)
- **Pattern**: Task delegation ve result synthesis'in ayrılması

---

## İmplementasyon: İki Yaklaşım

### Yaklaşım 1: Split Supervisors (Önerilen)

**Avantajlar:**
- Net sorumluluk ayrımı
- Her supervisor kendi prompt'una sahip
- Kolay debug ve test

**Dezavantajlar:**
- Biraz daha fazla node

#### Graph Yapısı

```python
START
  ↓
router_supervisor (routing agent seçer)
  ↓
  ├→ routing_agent → synthesizer_supervisor
  └→ chat_agent → synthesizer_supervisor
                   ↓
               synthesizer_supervisor (cevap üretir/iletir)
                   ↓
                  END
```

#### Config

```yaml
supervisor:
  routing:
    type: router
    strategy: handoff  # handoff tools kullan

  synthesis:
    type: synthesizer
    strategy: transparent  # transparent | synthesized | adaptive
```

#### Code Yapısı

```python
# Router Supervisor - Sadece routing
router_supervisor = create_agent(
    model=llm,
    tools=[assign_to_chat_agent, assign_to_routing_agent],
    system_prompt=ROUTER_SUPERVISOR_PROMPT,  # Routing'e odaklanır
    name="router_supervisor"
)

# Synthesizer Supervisor - Sadece synthesis
synthesizer_supervisor = create_agent(
    model=llm,
    tools=[forward_message, synthesize_response],  # Yeni tools
    system_prompt=SYNTHESIZER_SUPERVISOR_PROMPT,  # Synthesis'e odaklanır
    name="synthesizer_supervisor"
)

builder.add_node("router_supervisor", router_supervisor,
                 destinations=["routing", "chat"])
builder.add_node("synthesizer_supervisor", synthesizer_supervisor)
```

---

### Yaklaşım 2: Context-Aware Single Supervisor

**Avantajlar:**
- Tek supervisor
- State-based davranış değişimi
- Daha az node

**Dezavantajlar:**
- Prompt karmaşıklaşır
- Sorumluluklar iç içe

#### Graph Yapısı

```python
START
  ↓
supervisor (mode: routing)
  ↓
  ├→ routing_agent
  └→ chat_agent
       ↓
supervisor (mode: synthesis)
  ↓
END
```

#### Config

```yaml
supervisor:
  mode: two_tier  # single | two_tier
  synthesis_strategy: adaptive  # transparent | synthesized | adaptive
```

#### Code Yapısı

```python
def should_synthesize(state: MessagesState) -> str:
    """Agent cevabından sonra synthesis gerekli mi?"""
    config = state.get("config", {})
    strategy = config.get("synthesis_strategy", "transparent")

    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None

    # Tool message ise agent cevap vermiş
    if isinstance(last_message, ToolMessage):
        if strategy == "transparent":
            return END  # Direkt bitir
        elif strategy == "synthesized":
            return "supervisor"  # Supervisor sentezlesin
        elif strategy == "adaptive":
            # Agent başarılı mı kontrol et
            if is_successful_agent_response(state):
                return END
            else:
                return "supervisor"  # Düzelt/sentezle

    return END

builder.add_conditional_edges(
    "routing",
    should_synthesize,
    {END: END, "supervisor": "supervisor"}
)
```

---

## Detaylı İmplementasyon: Split Supervisors (Önerilen)

### 1. Prompts

#### Router Supervisor

```python
ROUTER_SUPERVISOR_PROMPT = """You are a ROUTING SUPERVISOR.

Your ONLY job is to:
1. Analyze user intent
2. Select the appropriate specialist agent
3. Forward the request using handoff tools

You do NOT:
- Generate responses yourself
- Synthesize or summarize
- Add commentary

Available agents:
- ROUTING AGENT: Navigation, page finding, document retrieval
- CHAT AGENT: Conversation, questions, general discussion

Use the appropriate handoff tool immediately."""
```

#### Synthesizer Supervisor

```python
SYNTHESIZER_SUPERVISOR_PROMPT = """You are a SYNTHESIS SUPERVISOR.

Your job is to:
1. Receive results from specialist agents
2. Decide: forward directly OR synthesize

Strategy modes:
- TRANSPARENT: Forward agent response directly (use forward_message tool)
- SYNTHESIZED: Analyze and create unified response
- ADAPTIVE: Forward if good, synthesize if needs improvement

Current mode: {synthesis_strategy}

Guidelines:
- If agent response is complete and clear → FORWARD
- If multiple agents involved or needs context → SYNTHESIZE
- If agent response has issues → IMPROVE and synthesize"""
```

### 2. Tools

#### Forward Message Tool

```python
from langchain_core.tools import tool
from langchain_core.messages import AIMessage

@tool
def forward_message(state: dict) -> dict:
    """
    Forward the last agent message directly to user without modification.

    Use this when agent response is complete and needs no synthesis.
    """
    messages = state.get("messages", [])

    # Son agent mesajını bul
    last_agent_message = None
    for msg in reversed(messages):
        if isinstance(msg, (AIMessage, ToolMessage)):
            last_agent_message = msg
            break

    if last_agent_message:
        logger.info("[SYNTHESIZER] Forwarding message directly")
        # Mesajı olduğu gibi bırak
        return {"messages": messages}

    logger.warning("[SYNTHESIZER] No agent message to forward")
    return {"messages": messages}
```

#### Synthesize Response Tool

```python
@tool
def synthesize_response(state: dict, synthesis_instruction: str = None) -> dict:
    """
    Synthesize agent responses into a unified response.

    Args:
        state: Current state with messages
        synthesis_instruction: Optional specific synthesis instruction

    Use this when:
    - Multiple agents provided responses
    - Agent response needs context or clarification
    - Response needs formatting or improvement
    """
    messages = state.get("messages", [])

    # Agent mesajlarını topla
    agent_responses = []
    for msg in messages:
        if isinstance(msg, (AIMessage, ToolMessage)):
            agent_responses.append(msg.content)

    logger.info(f"[SYNTHESIZER] Synthesizing {len(agent_responses)} agent responses")

    # LLM'e synthesis yaptır (bu fonksiyon supervisor'ın kendi response'ını tetikler)
    # Bu durumda tool sadece state'i döndürür, supervisor sonraki çağrıda cevap üretir
    state["synthesis_requested"] = True
    state["synthesis_instruction"] = synthesis_instruction

    return state
```

### 3. Graph Builder

```python
def build_two_tier_supervisor_graph(llm: LLM) -> StateGraph:
    """Build two-tier supervisor graph."""

    # Agents
    router_supervisor = create_agent(
        model=llm.get_chat(),
        tools=[assign_to_chat_agent, assign_to_routing_agent],
        system_prompt=ROUTER_SUPERVISOR_PROMPT,
        name="router_supervisor"
    )

    synthesizer_supervisor = create_agent(
        model=llm.get_chat(),
        tools=[forward_message, synthesize_response],
        system_prompt=SYNTHESIZER_SUPERVISOR_PROMPT,
        name="synthesizer_supervisor"
    )

    routing_agent = RoutingGraph(llm=llm).build_graph()
    chat_agent = ChatGraph(llm=llm).build_graph()

    # Build graph
    builder = StateGraph(MessagesState)

    # Nodes
    builder.add_node("router_supervisor", router_supervisor,
                     destinations=["routing", "chat"])
    builder.add_node("routing", handle_routing_node(routing_agent))
    builder.add_node("chat", chat_agent)
    builder.add_node("synthesizer_supervisor", synthesizer_supervisor)

    # Edges
    builder.add_edge(START, "router_supervisor")
    builder.add_edge("routing", "synthesizer_supervisor")
    builder.add_edge("chat", "synthesizer_supervisor")
    builder.add_edge("synthesizer_supervisor", END)

    return builder.compile()
```

---

## Strategy Karşılaştırması

| Strategy | Router | Synthesizer | Use Case |
|----------|--------|-------------|----------|
| **Transparent** | Routing yapar | Forward eder (sessiz) | Basit routing, net agent cevapları |
| **Synthesized** | Routing yapar | Her zaman sentezler | Multi-agent, tutarlılık gerekli |
| **Adaptive** | Routing yapar | Duruma göre karar verir | Esnek, kalite kontrolü |

### Adaptive Strategy Logic

```python
def should_synthesize_adaptive(state: MessagesState) -> bool:
    """Adaptive strategy: agent cevabını analiz et."""
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None

    if not isinstance(last_message, (AIMessage, ToolMessage)):
        return False

    content = str(last_message.content)

    # Synthesis gerektiren durumlar
    needs_synthesis = (
        # Çok kısa cevap
        len(content) < 50 or
        # Error içeriyor
        "error" in content.lower() or
        # URL var ama açıklama yok
        ("http" in content and len(content) < 100) or
        # Multiple agent calls olmuş
        len([m for m in messages if isinstance(m, ToolMessage)]) > 1
    )

    return needs_synthesis
```

---

## Migration Path

### Phase 1: Config Ekleme
```yaml
supervisor:
  architecture: single  # single | two_tier
  synthesis_strategy: transparent
```

### Phase 2: Forward Message Tool Ekleme
Synthesizer supervisor için `forward_message` tool'u ekle

### Phase 3: Prompts Ayırma
Router ve Synthesizer prompt'larını ayır

### Phase 4: Two-Tier Graph Oluşturma
Split supervisor graph'ı build et

### Phase 5: Test ve Rollout
A/B test ile karşılaştır

---

## Best Practices

### Router Supervisor
- ✅ Sadece routing logic
- ✅ Minimal prompt
- ✅ Hızlı karar
- ❌ Cevap üretme
- ❌ Synthesis

### Synthesizer Supervisor
- ✅ Cevap kalitesi kontrol
- ✅ Forward vs synthesize kararı
- ✅ Context ekleme
- ❌ Agent seçimi
- ❌ Routing logic

### Performance
- Transparent: ~1 LLM call (router)
- Synthesized: ~2 LLM calls (router + synthesizer)
- Adaptive: ~1-2 LLM calls (conditional)

---

## Kaynaklar

- [LangGraph Hierarchical Agent Teams](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/hierarchical_agent_teams/)
- [LangGraph Multi-Agent Workflows](https://blog.langchain.com/langgraph-multi-agent-workflows/)
- [AutoGen Orchestrator-Worker Pattern](https://medium.com/oracle-saas-paas/autogen-orchestrator-worker-agents-design-pattern-eef8698459b2)
- [Azure AI Agent Design Patterns](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns)
- [Kore.ai Supervisor Pattern](https://docs.kore.ai/agent-platform/ai-agents/supervisor/)
- [Agent Orchestration Patterns](https://www.getdynamiq.ai/post/agent-orchestration-patterns-in-multi-agent-systems-linear-and-adaptive-approaches-with-dynamiq)
