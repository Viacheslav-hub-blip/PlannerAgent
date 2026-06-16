# Models

`instances.py` содержит центральную Python-настройку моделей:

- `build_main_model()` — основная LLM для обычных запусков;
- `build_local_ui_model()` — LLM для локального LangGraph UI;
- `build_qwen_vlm_config()` и `build_qwen_vlm_client()` — Qwen VLM для
  `analyze_image`;
- `build_openai_embeddings()` и `build_optional_gigachat()` — дополнительные клиенты.

`vlm.py` содержит клиентскую механику Qwen VLM и кодирование изображения в base64.
Root `model.py` оставлен compatibility shim для старых импортов.
