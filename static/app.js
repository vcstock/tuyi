"use strict";

const field = (id) => document.getElementById(id);
let options;
let image;
let sourceUrl;
let resultUrl;
let pending;
let webJob;

function setOptions(id, values) {
  field(id).replaceChildren(...values.map((name) => new Option(name, name)));
}

function serviceChanged() {
  const provider = field("provider").value;
  const model = options.providers[provider];
  field("key-field").hidden = !model;
  field("model-field").hidden = !model;
  field("web-help").hidden = Boolean(model);
  field("key").value = "";
  field("model").value = "";
  field("model").placeholder = model?.model || "火山方舟模型 ID / 接入点";
}

function message(text) {
  field("status").textContent = text;
}

function clearResult() {
  if (resultUrl) URL.revokeObjectURL(resultUrl);
  resultUrl = undefined;
  field("result-preview").removeAttribute("src");
  field("result-preview").hidden = true;
  field("result-empty").hidden = false;
  field("result-empty").textContent = "翻译完成后在这里预览";
  field("output-info").textContent = "";
  field("download").hidden = true;
}

function importImage(file) {
  if (!file) return;
  if (file.size > 19 * 1024 * 1024) {
    message("请上传小于 19 MiB 的图片。");
    return;
  }
  pending?.abort();
  webJob = undefined;
  image = file;
  if (sourceUrl) URL.revokeObjectURL(sourceUrl);
  sourceUrl = URL.createObjectURL(file);
  clearResult();
  field("source-name").textContent = file.name;
  field("source-preview").src = sourceUrl;
  field("source-preview").hidden = false;
  field("source-empty").hidden = true;
  field("translate").disabled = !options;
  message("图片已载入。选择目标语言后开始翻译。");
}

function makeJob(action, jobImage = image) {
  const data = new FormData();
  data.append("image", jobImage, jobImage.name || "clipboard.png");
  for (const name of ["provider", "language", "instructions", "key", "model", "format", "scale", "quality"]) {
    data.append(name, field(name).value);
  }
  data.set("text_scale", field("text-scale").value);
  data.set("action", action);
  if (action !== "translate") data.delete("key");
  return data;
}

function displayResult(blob, dimensions, data) {
  clearResult();
  resultUrl = URL.createObjectURL(blob);
  const preview = field("result-preview");
  preview.src = resultUrl;
  preview.hidden = false;
  field("result-empty").hidden = true;
  const size = blob.size >= 1048576 ? (blob.size / 1048576).toFixed(2) + " MiB"
    : (blob.size / 1024).toFixed(1) + " KiB";
  field("output-info").textContent = dimensions.replace("x", " × ") + " px · " + size;
  const extensions = {PNG: "png", JPG: "jpg", WebP: "webp", AVIF: "avif", TIFF: "tiff",
    BMP: "bmp", GIF: "gif", SVG: "svg", SVGZ: "svgz"};
  const rawName = data.get("image").name;
  const name = (rawName.replace(/\.[^.]+$/, "").replace(/[<>:"/\\|?*]/g, "_").slice(0, 80) || "image");
  const timestamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");
  const download = field("download");
  download.href = resultUrl;
  download.download = name + "_" + timestamp + "." + extensions[data.get("format")];
  download.hidden = false;
}

async function submit(data) {
  pending?.abort();
  const controller = new AbortController();
  pending = controller;
  const action = data.get("action");
  field("translate").disabled = true;
  field("render").disabled = true;
  const feedback = field("reply-error");
  feedback.textContent = "";
  if (action === "render") feedback.textContent = "正在生成译图…";
  else message(action === "prepare" ? "正在识别文字…" : "正在识别文字并请求翻译服务…");
  try {
    const response = await fetch("/api/image", {method: "POST", body: data, signal: controller.signal});
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      throw new Error(problem.error || "请求失败，HTTP " + response.status);
    }
    if (action === "prepare") {
      const body = await response.json();
      webJob = data;
      field("prompt").value = body.prompt;
      field("reply").value = "";
      field("reply-note").textContent = "在官网发送提示词，然后粘贴对应的 " + body.lines + " 条译文。";
      field("open-provider").href = options.web[data.get("provider")];
      field("reply-dialog").showModal();
      message("已识别文字，等待网页译文。");
    } else {
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      displayResult(blob, response.headers.get("X-Image-Dimensions") || "", data);
      if (action === "render") field("reply-dialog").close();
      message("译图已生成，可下载。");
    }
  } catch (error) {
    if (error.name !== "AbortError") {
      if (action === "render") feedback.textContent = error.message;
      else message(error.message);
    }
  } finally {
    if (pending === controller) {
      pending = undefined;
      field("translate").disabled = !image;
      field("render").disabled = false;
    }
  }
}

field("provider").addEventListener("change", serviceChanged);
field("pick-file").addEventListener("click", () => field("file").click());
field("file").addEventListener("change", (event) => {
  importImage(event.target.files[0]);
  event.target.value = "";
});
document.addEventListener("paste", (event) => {
  if (event.target.matches?.("input, textarea, select") || field("reply-dialog").open) return;
  const file = [...event.clipboardData.files].find((item) => item.type.startsWith("image/"));
  if (file) {
    event.preventDefault();
    importImage(file);
  }
});
const drop = field("previews");
drop.addEventListener("dragover", (event) => {
  event.preventDefault();
  field("drop").classList.add("is-over");
});
drop.addEventListener("dragleave", () => field("drop").classList.remove("is-over"));
drop.addEventListener("drop", (event) => {
  event.preventDefault();
  field("drop").classList.remove("is-over");
  importImage(event.dataTransfer.files[0]);
});
field("source-preview").addEventListener("error", () => {
  field("source-preview").hidden = true;
  field("source-empty").hidden = false;
  field("source-empty").textContent = "浏览器无法预览此格式，仍可开始翻译。";
});
field("result-preview").addEventListener("error", () => {
  field("result-preview").hidden = true;
  field("result-empty").hidden = false;
  field("result-empty").textContent = "浏览器无法预览此格式，译图可以下载。";
});
field("toggle").addEventListener("click", () => {
  const original = field("original");
  original.hidden = !original.hidden;
  field("toggle").textContent = original.hidden ? "显示原图" : "收起原图";
});
field("format").addEventListener("change", () => {
  field("quality-field").hidden = field("format").value !== "JPG";
});
field("workbench").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!image || !options) return;
  const provider = field("provider").value;
  submit(makeJob(provider in options.web ? "prepare" : "translate"));
});
field("copy-prompt").addEventListener("click", async () => {
  const prompt = field("prompt");
  try {
    await navigator.clipboard.writeText(prompt.value);
    field("reply-error").textContent = "提示词已复制。";
  } catch {
    prompt.select();
    field("reply-error").textContent = "提示词已选中。请按 Ctrl+C 或 ⌘+C 复制。";
  }
});
field("cancel-reply").addEventListener("click", () => field("reply-dialog").close());
field("reply-dialog").addEventListener("close", () => {
  if (field("render").disabled && pending) pending.abort();
});
field("render").addEventListener("click", () => {
  if (!webJob) return;
  const data = makeJob("render", webJob.get("image"));
  data.set("provider", webJob.get("provider"));
  data.set("language", webJob.get("language"));
  data.set("reply", field("reply").value);
  submit(data);
});

fetch("/api/options").then((response) => {
  if (!response.ok) throw new Error();
  return response.json();
}).then((data) => {
  options = data;
  setOptions("provider", [...Object.keys(data.providers), ...Object.keys(data.web)]);
  setOptions("language", data.languages);
  setOptions("format", data.formats);
  serviceChanged();
  field("translate").disabled = !image;
}).catch(() => message("无法读取服务设置。请检查部署后重新加载。"));
