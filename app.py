import os
import re
import gc
import json
import shutil
import asyncio
import psutil
import requests
import tempfile
import subprocess
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from ocr_engine import process_vector_pdf_sync

try:
    import pynvml
    pynvml.nvmlInit()
    NVML_AVAILABLE = True
except Exception:
    NVML_AVAILABLE = False

app = FastAPI()
templates = Jinja2Templates(directory="templates")

STORAGE_DIR = "/tmp/pdf_translations"
os.makedirs(STORAGE_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STORAGE_DIR), name="static")

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
GITHUB_REPO = os.getenv("GITHUB_REPO", "Baxterino/PDF_AI_Translation_Pipeline")
CURRENT_VERSION_FILE = "/app_host_mount/.version"

FONT_MAP = {
    "liberation_serif": "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "roboto": "/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Regular.ttf"
}

LANG_CODE_MAP = {
    "english": "en",
    "en": "en",
    "romanian": "ro",
    "ro": "ro"
}

def get_current_local_version():
    if os.path.exists(CURRENT_VERSION_FILE):
        try:
            with open(CURRENT_VERSION_FILE, "r") as f:
                return f.read().strip()
        except Exception:
            pass
    return "initial"

def get_ollama_active_process():
    try:
        res = requests.get(f"{OLLAMA_URL}/api/ps", timeout=1.5)
        models = res.json().get("models", [])
        if models:
            m = models[0]
            total_size = m.get("size", 0)
            vram_size = m.get("size_vram", 0)
            
            if total_size > 0:
                gpu_ratio = round((vram_size / total_size) * 100)
                cpu_ratio = 100 - gpu_ratio
                if gpu_ratio >= 100:
                    proc_str = "100% GPU"
                elif gpu_ratio <= 0:
                    proc_str = "100% CPU"
                else:
                    proc_str = f"{cpu_ratio}%/{gpu_ratio}% CPU/GPU"
            else:
                proc_str = "100% GPU"

            return {
                "active": True,
                "name": m.get("name", "Unknown"),
                "size_gb": f"{round(total_size / (1024 ** 3), 1)} GB",
                "vram_gb": round(vram_size / (1024 ** 3), 2),
                "processor": proc_str,
                "context": m.get("context_length", 4096)
            }
    except Exception:
        pass
    return {"active": False, "name": "Idle / Standby", "size_gb": "--", "vram_gb": 0.0, "processor": "--", "context": "--"}

def get_vram_stats(ollama_telemetry):
    if NVML_AVAILABLE:
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            used = round(mem.used / (1024 ** 3), 2)
            total = round(mem.total / (1024 ** 3), 2)
            if used > 0:
                return {
                    "vendor": "NVIDIA",
                    "name": name,
                    "used_gb": used,
                    "total_gb": total,
                    "percent": round((mem.used / mem.total) * 100, 1)
                }
        except Exception:
            pass

    for smi_cmd in ["nvidia-smi", "/usr/lib/wsl/lib/nvidia-smi"]:
        try:
            res = subprocess.check_output(
                [smi_cmd, "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"],
                encoding="utf-8", stderr=subprocess.DEVNULL
            ).strip().split("\n")[0].split(",")
            name = res[0].strip()
            used_mb = float(res[1].strip())
            total_mb = float(res[2].strip())
            used_gb = round(used_mb / 1024, 2)
            total_gb = round(total_mb / 1024, 2)
            if used_gb > 0:
                return {
                    "vendor": "NVIDIA",
                    "name": name,
                    "used_gb": used_gb,
                    "total_gb": total_gb,
                    "percent": round((used_mb / total_mb) * 100, 1)
                }
        except Exception:
            pass

    if ollama_telemetry.get("active") and ollama_telemetry.get("vram_gb", 0) > 0:
        return {
            "vendor": "NVIDIA",
            "name": "GPU Mode (Dedicated VRAM)",
            "used_gb": ollama_telemetry["vram_gb"],
            "total_gb": 8.0,
            "percent": 0.0
        }

    return {
        "vendor": "None",
        "name": "GPU Mode (Dedicated VRAM)",
        "used_gb": 0.0,
        "total_gb": 8.0,
        "percent": 0.0
    }

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/queue", response_class=HTMLResponse)
async def queue_page(request: Request):
    return templates.TemplateResponse("queue.html", {"request": request})

@app.get("/text", response_class=HTMLResponse)
async def text_translator_page(request: Request):
    return templates.TemplateResponse("text.html", {"request": request})

@app.get("/ocr", response_class=HTMLResponse)
async def ocr_page(request: Request):
    return templates.TemplateResponse("ocr.html", {"request": request})

@app.get("/api/stats")
async def get_system_stats():
    ram = psutil.virtual_memory()
    ollama_ps = get_ollama_active_process()
    vram = get_vram_stats(ollama_ps)
    return {
        "ram": {
            "used_gb": round(ram.used / (1024 ** 3), 2),
            "total_gb": round(ram.total / (1024 ** 3), 2),
            "percent": ram.percent
        },
        "vram": vram,
        "ollama_ps": ollama_ps
    }

@app.get("/api/models")
async def get_models():
    models_data = []
    try:
        res = requests.get(f"{OLLAMA_URL}/api/tags", timeout=4)
        for m in res.json().get("models", []):
            models_data.append({
                "name": m["name"],
                "size_gb": round(m.get("size", 0) / (1024 ** 3), 2)
            })
    except Exception:
        pass
    return {"models": models_data}

@app.get("/api/check-update")
async def check_update():
    current_ver = get_current_local_version()
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/commits/main"
        res = requests.get(url, headers={"User-Agent": "FastAPI-Pipeline-Updater"}, timeout=4.0)
        if res.status_code == 200:
            commit_data = res.json()
            remote_sha = commit_data.get("sha", "")[:7]
            commit_msg = commit_data.get("commit", {}).get("message", "").split("\n")[0]
            
            update_available = (remote_sha != current_ver and current_ver != "dev")
            return JSONResponse({
                "configured": True,
                "current_version": current_ver,
                "latest_version": remote_sha,
                "commit_message": commit_msg,
                "update_available": update_available
            })
    except Exception as e:
        return JSONResponse({
            "configured": True,
            "current_version": current_ver,
            "update_available": False,
            "error": str(e)
        })

    return JSONResponse({
        "configured": True,
        "current_version": current_ver,
        "update_available": False,
        "message": "Could not connect to GitHub repository."
    })

@app.post("/api/apply-update")
async def apply_update():
    async def run_updater():
        await asyncio.sleep(0.5)
        subprocess.Popen(
            "nohup /bin/bash /app_host_mount/update.sh > /dev/null 2>&1 &",
            shell=True,
            cwd="/app_host_mount",
            start_new_session=True
        )

    asyncio.create_task(run_updater())
    return JSONResponse({
        "status": "updating",
        "message": "Update initiated! Rebuilding containers..."
    })

@app.post("/api/purge")
async def purge_system():
    try:
        res = requests.get(f"{OLLAMA_URL}/api/ps", timeout=2.0)
        loaded = res.json().get("models", [])
        for m in loaded:
            requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": m.get("name"), "keep_alive": 0},
                timeout=3.0
            )
    except Exception:
        pass

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = " ".join(proc.info.get('cmdline') or [])
            if "pdf2zh" in cmdline and proc.pid != os.getpid():
                proc.kill()
        except Exception:
            pass

    for item in os.listdir(STORAGE_DIR):
        item_path = os.path.join(STORAGE_DIR, item)
        try:
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)
        except Exception:
            pass

    gc.collect()

    async def delayed_restart():
        await asyncio.sleep(0.5)
        os._exit(0)

    asyncio.create_task(delayed_restart())

    return JSONResponse({
        "status": "success",
        "message": "Memory purged, cache cleared, container restarted."
    })

@app.post("/api/translate-text")
async def direct_text_translation(
    text: str = Form(...),
    model: str = Form(...),
    lang_in: str = Form("english"),
    lang_out: str = Form("romanian")
):
    src_title = lang_in.capitalize()
    tgt_title = lang_out.capitalize()
    
    system_prompt = (
        f"You are a professional, accurate translator. "
        f"Translate the provided text from {src_title} to {tgt_title}. "
        f"Output ONLY the translated text without adding commentary, notes, greetings, or preamble."
    )

    async def stream_ollama():
        try:
            req = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": model,
                    "system": system_prompt,
                    "prompt": text,
                    "stream": True
                },
                stream=True,
                timeout=120
            )
            for line in req.iter_lines():
                if line:
                    chunk = json.loads(line.decode("utf-8"))
                    yield f"data: {json.dumps({'response': chunk.get('response', ''), 'done': chunk.get('done', False)})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

    return StreamingResponse(stream_ollama(), media_type="text/event-stream")

@app.post("/api/ocr-process")
async def start_ocr_process(file: UploadFile = File(...)):
    session_id = tempfile.mkdtemp(dir=STORAGE_DIR)
    input_file_path = os.path.join(session_id, file.filename)
    clean_name = os.path.splitext(file.filename)[0] + "_Vector.pdf"
    output_file_path = os.path.join(session_id, clean_name)

    with open(input_file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    async def event_stream():
        loop = asyncio.get_event_loop()
        queue = asyncio.Queue()

        def progress_callback(current, total):
            pct = int((current / total) * 100)
            asyncio.run_coroutine_threadsafe(
                queue.put({"type": "progress", "value": pct, "info": f"Processing Page {current} of {total}"}),
                loop
            )

        async def run_worker():
            try:
                await loop.run_in_executor(
                    None, 
                    process_vector_pdf_sync, 
                    input_file_path, 
                    output_file_path, 
                    progress_callback
                )
                await queue.put({"type": "done"})
            except Exception as e:
                await queue.put({"type": "error", "message": str(e)})

        asyncio.create_task(run_worker())

        while True:
            item = await queue.get()
            if item["type"] == "progress":
                yield f"data: {json.dumps(item)}\n\n"
            elif item["type"] == "done":
                orig_url = f"/static/{os.path.basename(session_id)}/{os.path.basename(input_file_path)}"
                mod_url = f"/static/{os.path.basename(session_id)}/{clean_name}"
                yield f"data: {json.dumps({'type': 'done', 'original': orig_url, 'modified': mod_url})}\n\n"
                break
            elif item["type"] == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': item['message']})}\n\n"
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.post("/api/translate")
async def start_translation(
    file: UploadFile = File(...),
    model: str = Form(...),
    lang_in: str = Form("english"),
    lang_out: str = Form("romanian"),
    font_choice: str = Form("liberation_serif")
):
    session_id = tempfile.mkdtemp(dir=STORAGE_DIR)
    file_path = os.path.join(session_id, file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    font_path = FONT_MAP.get(font_choice, FONT_MAP["liberation_serif"])
    if font_choice == "roboto" and not os.path.exists(font_path):
        font_path = "/usr/share/fonts/truetype/roboto/Roboto-Regular.ttf"

    raw_out = lang_out.lower().strip()
    fallback_code = LANG_CODE_MAP.get(raw_out, "ro")

    async def event_stream():
        env = os.environ.copy()
        env["OLLAMA_HOST"] = OLLAMA_URL
        env["PYTHONUNBUFFERED"] = "1"
        env["MALLOC_CHECK_"] = "0"
        env["MALLOC_PERTURB_"] = "0"
        
        if font_path and os.path.exists(font_path):
            env["PDF2ZH_CUSTOM_FONT"] = font_path

        cmd = [
            "pdf2zh", file_path,
            "--service", f"ollama:{model}",
            "-li", lang_in,
            "-lo", lang_out,
            "--thread", "1",
            "--skip-subset-fonts",
            "--compatible"
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=session_id,
            env=env
        )

        progress_regex = re.compile(r"(\d+)%\|")
        blocks_regex = re.compile(r"(\d+)/(\d+)")
        timing_regex = re.compile(r"\[([0-9:]+)<([0-9:?]+)(?:,\s*([^\]]+))?\]")

        buffer = ""
        while True:
            char = await proc.stdout.read(1)
            if not char:
                break
            
            char_str = char.decode("utf-8", errors="ignore")
            if char_str in ["\r", "\n"]:
                line = buffer.strip()
                buffer = ""
                if not line:
                    continue

                prog_match = progress_regex.search(line)
                block_match = blocks_regex.search(line)
                time_match = timing_regex.search(line)

                if prog_match:
                    pct = int(prog_match.group(1))
                    block_info = f"Translating block {block_match.group(1)} of {block_match.group(2)}" if block_match else f"{pct}%"
                    
                    elapsed = time_match.group(1) if (time_match and time_match.group(1)) else ""
                    remaining = time_match.group(2) if (time_match and time_match.group(2)) else ""
                    speed = time_match.group(3) if (time_match and time_match.group(3)) else ""

                    payload = {
                        "type": "progress",
                        "value": pct,
                        "info": block_info,
                        "elapsed": elapsed,
                        "remaining": remaining,
                        "speed": speed,
                        "raw": line
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'log', 'message': line})}\n\n"
            else:
                buffer += char_str

        await proc.wait()

        mono_pdf, dual_pdf = None, None
        for f in os.listdir(session_id):
            if f.endswith("-zh.pdf") or f.endswith(f"-{raw_out}.pdf") or f.endswith(f"-{fallback_code}.pdf") or f.endswith("-mono.pdf"):
                mono_pdf = f"/static/{os.path.basename(session_id)}/{f}"
            elif f.endswith("-dual.pdf"):
                dual_pdf = f"/static/{os.path.basename(session_id)}/{f}"

        if not mono_pdf and not dual_pdf:
            yield f"data: {json.dumps({'type': 'error', 'message': 'PDF rendering crashed or was terminated. No output was generated.'})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'done', 'mono': mono_pdf, 'dual': dual_pdf})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
