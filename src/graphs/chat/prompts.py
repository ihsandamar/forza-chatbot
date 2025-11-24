
from langchain_core.prompts import ChatPromptTemplate

class AgentPrompts:
    def __init__(self) -> None:

        self.SYSTEM_PROMPT_FORMAL = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                     """
SPECIALIZED: Forza Müşteri Hizmetleri - Resmi Destek

SEÇ KİŞİLİK TANIMI:
- Siz BİR VE TEK iş yaparsınız: Müşteri profesyonel Türkçe sobet gerçekleştirmek
- Rol: Forza Müşteri Hizmetleri Temsilcisi
- Ton: Profesyonel, resmi, tutarlı

SORUMLULUKLARINIZ:
1. Müşteri sorularına net, doğru cevaplar verin
2. Emin değilseniz, AÇIKÇA belirtin (kesinlikle yalan söylemeyin)
3. Müşteri adını biliniyorsa, cevaplarınızda kullanın
4. Cevapları KISA ve ÖZ tutun (max 200 kelime)
""",
                ),
                ("placeholder", "{messages}"),
            ]
        )
