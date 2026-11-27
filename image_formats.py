import base64
import gzip
from io import BytesIO
import re
from xml.etree import ElementTree as ET

from PIL import Image


EXPORT_FORMATS = {
    "PNG": (".png", "PNG", {"compress_level": 7}),
    "JPG": (".jpg", "JPEG", {"subsampling": 2, "optimize": True, "progressive": True}),
    "WebP": (".webp", "WEBP", {"lossless": True}),
    "AVIF": (".avif", "AVIF", {"quality": 90}),
    "TIFF": (".tiff", "TIFF", {"compression": "tiff_deflate"}),
    "BMP": (".bmp", "BMP", {}),
    "GIF": (".gif", "GIF", {}),
    "SVG": (".svg", "SVG", {}),
    "SVGZ": (".svgz", "SVG", {}),
}
IMAGE_SUFFIXES = {suffix for suffix, _, _ in EXPORT_FORMATS.values()} | {
    ".jpeg", ".jfif", ".tif", ".ico", ".ppm", ".pgm", ".pbm", ".pnm", ".tga", ".qoi", ".dds",
}
IMAGE_LIMIT = 30_000_000
SVG_NAMESPACE = "http://www.w3.org/2000/svg"


def open_image(path):
    suffix = path.suffix.lower()
    if suffix not in {".svg", ".svgz"}:
        return Image.open(path)
    from resvg_py import svg_to_bytes

    opener = gzip.open if suffix == ".svgz" else open
    with opener(path, "rb") as source:
        markup = source.read(16 * 1024 * 1024 + 1)
    if len(markup) > 16 * 1024 * 1024 or b"<!DOCTYPE" in markup.upper():
        raise ValueError("SVG 文件过大或含有外部文档定义。")
    root = ET.fromstring(markup)
    if root.tag not in {"svg", "{" + SVG_NAMESPACE + "}svg"}:
        raise ValueError("文件中没有 SVG 图形。")
    for element in root.iter():
        for name, value in tuple(element.attrib.items()):
            if name.rsplit("}", 1)[-1] == "href" and not value.startswith(("#", "data:image/")):
                del element.attrib[name]
    viewbox = re.split(r"[\s,]+", root.get("viewBox", "").strip())
    dimensions = []
    for index, name in enumerate(("width", "height")):
        amount = re.fullmatch(r"([0-9.eE+-]+)(px|in|cm|mm|pt|pc|em|ex|q)?", root.get(name, ""))
        if amount:
            factor = {None: 1, "px": 1, "in": 96, "cm": 96/2.54, "mm": 96/25.4,
                      "pt": 96/72, "pc": 16, "em": 12, "ex": 12, "q": 96/101.6}[amount[2]]
            dimensions.append(float(amount[1]) * factor)
        else:
            dimensions.append(float(viewbox[index + 2]) if len(viewbox) == 4 else 512)
    if any(not 0 < value <= 24_000 for value in dimensions) or dimensions[0] * dimensions[1] > IMAGE_LIMIT:
        raise ValueError("SVG 尺寸超出可处理范围。")
    ET.register_namespace("", SVG_NAMESPACE)
    rendered = svg_to_bytes(svg_string=ET.tostring(root, encoding="unicode"))
    return Image.open(BytesIO(rendered))


def export_image(image, path, name, percent=100, jpg_quality=92):
    suffix, image_format, options = EXPORT_FORMATS[name]
    if percent != 100:
        dimensions = tuple(max(1, round(length * percent / 100)) for length in image.size)
        if dimensions[0] * dimensions[1] > IMAGE_LIMIT:
            raise ValueError("缩放后的图片超过 3000 万像素。")
        image = image.resize(dimensions, Image.Resampling.LANCZOS)
    if image_format in {"JPEG", "BMP"}:
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(image.convert("RGBA"))
        image = background.convert("RGB")
    if image_format == "JPEG":
        options = {**options, "quality": jpg_quality}
    if image_format != "SVG":
        image.save(path, format=image_format, **options)
        return
    data = BytesIO()
    image.save(data, format="PNG")
    embedded = base64.b64encode(data.getvalue()).decode("ascii")
    width, height = image.size
    markup = (f'<svg xmlns="{SVG_NAMESPACE}" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
              f'<image width="{width}" height="{height}" href="data:image/png;base64,{embedded}"/></svg>')
    payload = markup.encode("ascii")
    if suffix == ".svgz":
        payload = gzip.compress(payload, mtime=0)
    if hasattr(path, "write"):
        path.write(payload)
    else:
        with open(path, "wb") as output:
            output.write(payload)
