import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

from flask import Flask, jsonify, request, send_file, send_from_directory
from PIL import Image, ImageOps
import requests
from werkzeug.exceptions import RequestEntityTooLarge

from image_formats import EXPORT_FORMATS, IMAGE_LIMIT, export_image, open_image
from translation import (
    API_PROVIDERS, LANGUAGES, NETWORKS, OCR_MODES, WEB_PROVIDERS,
    parse_web_translation, recognize, repaint, translate, translation_prompt,
)

app = Flask(__name__, static_folder="static", static_url_path="/assets")
app.config.update(MAX_CONTENT_LENGTH=20 * 1024 * 1024, MAX_FORM_MEMORY_SIZE=256 * 1024)
ocr_lock = Lock()
KEY_ENV = {
    "DeepSeek API": "DEEPSEEK_API_KEY", "OpenAI API": "OPENAI_API_KEY",
    "豆包 API": "ARK_API_KEY", "Kimi API": "MOONSHOT_API_KEY", "Gemini API": "GEMINI_API_KEY",
}
FORMATS_MIME = {
    "PNG": "image/png", "JPG": "image/jpeg", "WebP": "image/webp", "AVIF": "image/avif",
    "TIFF": "image/tiff", "BMP": "image/bmp", "GIF": "image/gif",
    "SVG": "image/svg+xml", "SVGZ": "application/gzip",
}


@app.after_request
def response_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' blob: data:; frame-ancestors 'none'; form-action 'self'"
    )
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/api/options")
def options():
    return {"languages": list(LANGUAGES), "formats": list(EXPORT_FORMATS),
            "providers": {label: {"model": info[1]} for label, info in API_PROVIDERS.items()},
            "web": WEB_PROVIDERS}


def integer_field(name, default, minimum, maximum):
    try:
        value = int(request.form.get(name, default))
    except (ValueError, TypeError):
        raise ValueError(f"{name} 须为整数。") from None
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 范围为 {minimum}–{maximum}。")
    return value


def read_upload():
    upload = request.files.get("image")
    if upload is None or not upload.filename:
        raise ValueError("请选择或粘贴图片。")
    suffix = Path(upload.filename).suffix.lower()
    try:
        with TemporaryDirectory() as folder:
            path = Path(folder) / ("source" + (suffix if suffix in {".svg", ".svgz"} else ".img"))
            upload.save(path)
            with open_image(path) as image:
                if image.width * image.height > IMAGE_LIMIT:
                    raise ValueError("图片超过 3000 万像素。")
                return ImageOps.exif_transpose(image).convert("RGBA")
    except (OSError, SyntaxError, Image.DecompressionBombError):
        raise ValueError("无法读取图片。请检查文件格式或尺寸。") from None


@app.post("/api/image")
def process_image():
    provider = request.form.get("provider", "")
    language = request.form.get("language", "简体中文")
    action = request.form.get("action", "translate")
    instructions = request.form.get("instructions", "").strip()
    if action not in {"prepare", "render", "translate"} or language not in LANGUAGES or len(instructions) > 4000:
        return jsonify(error="请求参数无效。术语说明最多 4000 字。"), 400
    if action == "translate" and provider not in API_PROVIDERS or action != "translate" and provider not in WEB_PROVIDERS:
        return jsonify(error="请选择相应的 API 或网页登录服务。"), 400
    try:
        if action == "translate":
            key = request.form.get("key", "").strip() or os.getenv(KEY_ENV[provider], "")
            if not key or len(key) > 1024 or any(char in key for char in "\r\n"):
                raise ValueError("请输入有效的 API Key，或让管理员配置该服务。")
            model = request.form.get("model", "").strip()
            if len(model) > 200:
                raise ValueError("模型 ID 太长。")
        image = read_upload()
        with ocr_lock:
            regions = recognize(image, OCR_MODES[1])
        if not regions:
            raise ValueError("未识别到文字。可试用清晰的中文或拉丁字母图片。")
        source_lines = [text for _, text in regions]
        if action == "prepare":
            return {"prompt": translation_prompt(source_lines, language, instructions), "lines": len(regions)}
        if action == "render":
            reply = request.form.get("reply", "")
            if len(reply) > 100_000:
                raise ValueError("网页回复过长。")
            translated = parse_web_translation(reply, len(regions))
        else:
            translated = translate(source_lines, language, provider, key, NETWORKS[0], "", model, instructions)
        name = request.form.get("format", "PNG")
        if name not in EXPORT_FORMATS:
            raise ValueError("不支持所选的导出格式。")
        percent = integer_field("scale", "100", 1, 400)
        result = repaint(image, regions, translated, LANGUAGES[language],
                         integer_field("text_scale", "100", 25, 200))
        data = io.BytesIO()
        export_image(result, data, name, percent, integer_field("quality", "92", 70, 100))
        length = data.tell()
        data.seek(0)
        out = send_file(data, mimetype=FORMATS_MIME[name], as_attachment=True,
                        download_name="translated" + EXPORT_FORMATS[name][0])
        out.headers["X-Image-Dimensions"] = "x".join(str(max(1, round(n * percent / 100))) for n in result.size)
        out.headers["X-Image-Bytes"] = str(length)
        return out
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
        return jsonify(error="无法连接翻译服务。请检查服务器网络或代理设置。"), 502
    except (ValueError, requests.exceptions.RequestException) as error:
        return jsonify(error=str(error) if isinstance(error, ValueError) else "翻译服务请求失败。"), 400
    except (IndexError, KeyError, TypeError):
        return jsonify(error="翻译服务返回了无法读取的响应。"), 502


@app.errorhandler(RequestEntityTooLarge)
def oversized(_):
    return jsonify(error="上传内容超过 20 MB。"), 413
