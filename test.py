# Command kullanım örneği

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt
from typing import TypedDict
from langgraph.checkpoint.memory import MemorySaver


class State(TypedDict):
    messages: list
    approval_needed: bool
    human_response: str

def approval_node(state):
    """Onay gerektiren kritik işlem"""
    print("[ROBOT] Kritik işlem yapılacak!")

    # Human'dan onay iste
    human_input = interrupt("[WARNING] Bu işlemi yapmayı onaylıyor musunuz? (evet/hayır)")

    return {
        "human_response": human_input,
        "approval_needed": False
    }

def action_node(state):
    """Onay sonrası işlem"""
    if state.get("human_response") == "evet":
        return {"messages": ["[OK] İşlem onaylandı ve yapıldı!"]}
    else:
        return {"messages": ["[ERROR] İşlem iptal edildi"]}

# Graph oluştur
graph = StateGraph(State)
graph.add_node("approval", approval_node)
graph.add_node("action", action_node)
graph.add_edge(START, "approval")
graph.add_edge("approval", "action")
graph.add_edge("action", END)

compiled = graph.compile(checkpointer=MemorySaver())

# === KULLANIM ===

# 1. İlk çalıştırma (interrupt'a kadar)
config = {"configurable": {"thread_id": "thread_1"}}
try:
    result = compiled.invoke({"messages": []}, config)
except:
    print("Graph durdu, onay bekleniyor...")

# 2. Graph state'ini kontrol et
current_state = compiled.get_state(config)
print(f"Interrupt mesajı: {current_state.tasks[0].interrupts[0].value}")

# 3. Command ile devam et
final_result = compiled.invoke(
    Command(resume="evet"),  # [FIRE] Command objesi - human response
    config
)

print(f"Final sonuç: {final_result}")