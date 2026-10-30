"""Provider presets; transport adapters remain independent of brand labels."""
from typing import Literal


def preset(title, purpose, url, protocol='openai_chat', **extra):
    return dict(title=title, purpose=purpose, url=url, protocol=protocol, **extra)


CATALOG = {
    'ollama':preset('Ollama','chat','http://ollama:11434','ollama',local=True),
    'openai_chat':preset('OpenAI Compatible','chat','https://api.openai.com/v1'),
    'openai_responses':preset('OpenAI Responses','chat','https://api.openai.com/v1','responses'),
    'anthropic':preset('Anthropic Compatible','chat','https://api.anthropic.com/v1','anthropic'),
    'deepseek':preset('DeepSeek','chat','https://api.deepseek.com'),
    'deepseek_responses':preset('DeepSeek Responses','chat','https://api.deepseek.com/v1','responses',hint='使用 DeepSeek Responses 接口，deepseek-flash 支持图片输入。'),
    'kimi':preset('Kimi','chat','https://api.moonshot.cn/v1'),
    'kimi_code':preset('Kimi Code Plan','chat','https://api.kimi.com/coding/v1',plan=True,
        hint='使用独立的 Code Plan 地址与密钥；订阅权益与适用场景以账号规定为准。'),
    'minimax':preset('MiniMax','chat','https://api.minimaxi.com/v1'),
    'minimax_token_plan':preset('MiniMax Token Plan','chat','https://api.minimaxi.com/v1',plan=True,
        hint='填写 Token Plan 专用密钥，与普通 API 连接分开管理。'),
    'zhipu':preset('Zhipu','chat','https://open.bigmodel.cn/api/paas/v4'),
    'xiaomi':preset('Xiaomi','chat','https://api.xiaomimimo.com/v1','xiaomi'),
    'xiaomi_token_plan':preset('Xiaomi Token Plan','chat','https://token-plan-cn.xiaomimimo.com/v1','xiaomi',plan=True,
        hint='使用套餐专用地址与密钥；该计划的场景限制以官方订阅说明为准。'),
    'xai':preset('xAI','chat','https://api.x.ai/v1'),
    'openrouter':preset('OpenRouter','chat','https://openrouter.ai/api/v1'),
    'azure_openai':preset('Azure OpenAI','chat','https://your-resource.openai.azure.com/openai/v1','azure',
        hint='填写资源的 /openai/v1 地址，模型名称填写部署名称；旧版部署接口可在高级设置填写 API 版本。'),
    'gemini_openai':preset('Gemini OpenAI API','chat','https://generativelanguage.googleapis.com/v1beta/openai'),
    'gemini_compatible':preset('Gemini Compatible','chat','https://generativelanguage.googleapis.com/v1beta','gemini',
        hint='使用 Gemini generateContent 协议，可连接原生或兼容服务。'),
    'openai_tts':preset('OpenAI TTS','tts','https://api.openai.com/v1','openai_tts',voice='alloy'),
    'xiaomi_tts':preset('小米 MiMo TTS','tts','https://api.xiaomimimo.com/v1','xiaomi_tts',voice='mimo_default'),
    'dashscope_tts':preset('阿里云百炼 TTS','tts','https://dashscope.aliyuncs.com/api/v1','dashscope_tts',
        hint='Qwen-Audio 模型填写业务空间的 API 地址；旧版 Qwen-TTS 可使用 DashScope 地域地址。'),
    'minimax_tts':preset('MiniMax TTS','tts','https://api.minimaxi.com/v1','minimax_tts'),
    'volcengine_tts':preset('火山引擎 TTS','tts','https://openspeech.bytedance.com','volcengine_tts',resource_id='seed-tts-2.0'),
    'azure_tts':preset('Azure TTS','tts','https://eastus.tts.speech.microsoft.com','azure_tts',voice='zh-CN-XiaoxiaoNeural',
        hint='地址中的区域须匹配 Speech 资源；也支持控制台提供的自定义资源域名。'),
    'gemini_tts':preset('Gemini TTS','tts','https://generativelanguage.googleapis.com/v1beta','gemini_tts',voice='Kore'),
    'xiaomi_stt':preset('小米 MiMo STT','stt','https://api.xiaomimimo.com/v1','xiaomi_stt'),
    'whisper_local_stt':preset('Whisper（Local）','stt','http://host.docker.internal:8001/v1','whisper',local=True,
        hint='连接在本机部署的 OpenAI 兼容 Whisper 服务，使用 /audio/transcriptions；不会自动下载或启动识别模型。'),
    'whisper_api_stt':preset('Whisper（API）','stt','https://api.openai.com/v1','whisper'),
    'xfyun_stt':preset('讯飞星火','stt','wss://iat.cn-huabei-1.xf-yun.com/v1','xfyun',
        hint='语音听写大模型 V2.0，需要 AppID、APIKey、APISecret，单条语音最长 60 秒。'),
    'openai_embedding':preset('OpenAI Embedding','embedding','https://api.openai.com/v1','openai_embedding'),
    'gemini_embedding':preset('Gemini Embedding','embedding','https://generativelanguage.googleapis.com/v1beta','gemini_embedding'),
    'ollama_embedding':preset('Ollama Embedding','embedding','http://ollama:11434','ollama_embedding',local=True),
    'dashscope_embedding':preset('DashScope Embedding','embedding','https://dashscope.aliyuncs.com/api/v1','dashscope_embedding'),
    'dashscope_rerank':preset('DashScope Rerank','rerank','https://dashscope.aliyuncs.com/api/v1','dashscope_rerank'),
    'xinference_rerank':preset('Xinference Rerank','rerank','http://host.docker.internal:9997/v1','xinference_rerank',local=True),
}
ProviderType = Literal[tuple(CATALOG)]


def protocol(provider):
    return CATALOG[provider.type]['protocol']
