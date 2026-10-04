import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from threading import BoundedSemaphore
import time

ROOT = Path(__file__).resolve().parents[1]
_MODEL_CAPACITY = BoundedSemaphore(2)


class ModelError(RuntimeError):
    pass


class ConfigurationError(ModelError):
    pass


def configuration():
    path = ROOT / "config.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        if not isinstance(config, dict):
            raise ValueError()
        for key in ("api_key", "base_url", "model"):
            if key in config and not isinstance(config[key], str):
                raise ValueError()
        if type(config.get("timeout_seconds", 90)) not in (int, float) or not 1 <= config.get("timeout_seconds", 90) <= 300:
            raise ValueError()
        if type(config.get("json_mode", True)) is not bool:
            raise ValueError()
    except (ValueError, OSError):
        raise ConfigurationError("config.json 格式无效，请参照 config.example.json。") from None
    return {
        "api_key": os.environ.get("FITNESS_API_KEY", config.get("api_key", "")),
        "base_url": os.environ.get("FITNESS_BASE_URL", config.get("base_url", "https://api.openai.com/v1")).rstrip("/"),
        "model": os.environ.get("FITNESS_MODEL", config.get("model", "gpt-4.1-mini")),
        "timeout_seconds": config.get("timeout_seconds", 90),
        "json_mode": config.get("json_mode", True),
    }


class ModelClient:
    def status(self):
        config = configuration()
        return {"configured": bool(config["api_key"]), "model": config["model"], "mode": "ai_agent"}

    def complete(self, messages):
        config = configuration()
        if not config["api_key"]:
            raise ConfigurationError("尚未配置模型。请在后端 config.json 填入 API Key，或设置 FITNESS_API_KEY。")
        parsed = urlparse(config["base_url"])
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
            raise ConfigurationError("模型地址必须使用 HTTPS，本地模型可使用 localhost HTTP。")
        body = {"model": config["model"], "messages": messages}
        if sum(len(message.get("content", "")) for message in messages) > 200_000:
            raise ModelError("模型上下文过长，请缩短训练记录或历史数据。")
        if config["json_mode"]:
            body["response_format"] = {"type": "json_object"}
        request = Request(config["base_url"] + "/chat/completions", data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                          headers={"Authorization": "Bearer " + config["api_key"], "Content-Type": "application/json"}, method="POST")
        if not _MODEL_CAPACITY.acquire(timeout=3):
            raise ModelError("模型调用繁忙，请稍后重试。")
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=config["timeout_seconds"]) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ModelError("模型响应超出大小限制。")
            envelope = json.loads(raw)
            choice = envelope["choices"][0]
            if choice.get("finish_reason") in {"length", "content_filter"}:
                raise ModelError("模型回答被截断或拒绝，请减少输入或检查模型配置。")
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ModelError("模型没有返回文本 JSON。")
            return content, {"model": envelope.get("model", config["model"]), "usage": envelope.get("usage", {}),
                             "latency_ms": round((time.perf_counter()-started)*1000)}
        except HTTPError as exc:
            raise ModelError(f"模型接口返回 HTTP {exc.code}；请检查 Key、模型名、余额与接口地址。") from None
        except (URLError, TimeoutError, OSError):
            raise ModelError("模型接口连接失败或超时。") from None
        except (KeyError, IndexError, json.JSONDecodeError, TypeError):
            raise ModelError("接口响应不符合 Chat Completions 格式。") from None
        finally:
            _MODEL_CAPACITY.release()
