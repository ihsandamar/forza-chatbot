import gradio as gr

def handle_message(history, message):
    # Yeni kullanıcı mesajını ekle
    history = history + [{"role": "user", "content": message}]

    # Eğer kullanıcı hava durumu ile ilgili bir şey yazdıysa dropdown'u göster
    if "hava" in message.lower():
        assistant_msg = {
            "role": "assistant",
            "content": "Hangi hava durumunu seçmek istersiniz?"
        }
        history.append(assistant_msg)

        # Dropdown'u görünür yap
        return history, gr.update(visible=True)

    # Normal yanıt
    assistant_msg = {"role": "assistant", "content": "Mesaj alındı."}
    history.append(assistant_msg)

    return history, gr.update(visible=False)


def handle_dropdown(history, selected):
    history = history + [
        {
            "role": "assistant",
            "content": f"Seçtiğiniz hava durumu: {selected}"
        }
    ]
    return history


with gr.Blocks() as demo:
    gr.Markdown("## 🗨️ ChatGPT-Style Bubble Chat + Tool Component")

    chatbot = gr.Chatbot(
        type="messages",
        layout="bubble",
        label="Chatbot"
    )

    user_input = gr.Textbox(label="Mesaj Yazın", placeholder="Bir şey yazın...")

    # Tool component — mesajın DIŞINDA (Gradio kuralı)
    weather_dropdown = gr.Dropdown(
        choices=["Sunny", "Rainy", "Cloudy", "Windy"],
        label="Hava Durumu",
        visible=False
    )

    # Kullanıcı Textbox gönderince çalışır
    user_input.submit(
        handle_message,
        [chatbot, user_input],
        [chatbot, weather_dropdown]
    )

    # Dropdown seçilince çalışır
    weather_dropdown.change(
        handle_dropdown,
        [chatbot, weather_dropdown],
        chatbot
    )

demo.launch()
