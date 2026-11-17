# Self-hosting

The supported backend is Linux with an NVIDIA GPU. The working reference used
Python 3.10, PaddlePaddle GPU 3.3.1 / CUDA 12.6 and an RTX 2080 Ti with 11 GB VRAM.
Other GPUs, operating systems and driver combinations need their own validation.
Keep Paddle and PyTorch in **separate virtual environments**.

## 1. Install dependencies

Install Python 3.10 with its venv package, an NVIDIA driver appropriate for CUDA
12.6, and `fonts-dejavu-core` from your Linux distribution. Then:

```bash
git clone https://github.com/Soarr01/TailScan.git
cd TailScan
python3.10 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install paddlepaddle-gpu==3.3.1 \
  -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
.venv/bin/python -m pip install -r server/requirements.txt

python3.10 -m venv .venv-images
.venv-images/bin/python -m pip install --upgrade pip
.venv-images/bin/python -m pip install torch==2.2.1 \
  --index-url https://download.pytorch.org/whl/cu121
.venv-images/bin/python -m pip install -r server/image_worker/requirements.txt
```

See the [Paddle installation guide](https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/linux-pip_en.html)
and [PyTorch previous versions](https://pytorch.org/get-started/previous-versions/)
when adapting the CUDA wheels to your environment. Do not install the image-worker
requirements into the Paddle environment: their NumPy versions intentionally differ.

## 2. Download assets

```bash
.venv/bin/python scripts/download_models.py --all
```

This downloads the pinned OCR checkpoint, DocQuadNet, DocRes, UVDoc source/weights,
and the DocShadow ONNX model. It also copies a system DejaVu Sans font for PDFs.
Weights are not stored in Git. Downloads require internet access and enough disk
space for the model files. PaddleOCR may fetch its additional layout assets on the
first OCR run. Review [third-party terms](../NOTICE.md) for the assets you use.

For a partial setup, `--images`, `--ocr` and `--font` can be selected individually.
The full configuration is the reference deployment; a missing optional model does
not provide that model's filter or dewarping function.

## 3. Start the API

```bash
cp .env.example .env
bash scripts/start_server.sh
```

The default paths are relative to the checkout. `.env` is optional; use it to point
to other virtual environments, model directories, worker ports, or a different
`TAILSCAN_GPU_IDLE_SECONDS` value. The main service stays on CPU. Model workers
start on demand and exit after five idle minutes, releasing their CUDA contexts.
The first OCR job after sleep takes longer because it reloads the model.

Open `http://127.0.0.1:8787/` locally. `GET /api/health` reports availability and GPU
state. `GET /api/gpu` is read-only; these polls do not reset the idle timer.
`POST /api/gpu/sleep` releases idle workers immediately and returns 409 during work.

## 4. Reach the server from iPhone

Install and connect Tailscale on both devices. On the server:

```bash
tailscale serve --bg --http=8088 http://127.0.0.1:8787
```

Use the private URL printed by Tailscale in Safari or in the app's server settings.
No developer's private server address is configured in this project. The API has a
single shared library and no built-in user authentication, so it is designed for
your trusted private network. See [Tailscale Serve](https://tailscale.com/kb/1242/tailscale-serve).

## Persistence and operations

- `server/library/`: saved PDFs, text, original pages, selected edits and filter caches.
  Back up this directory; it is outside temporary-job cleanup.
- `server/data/`: temporary jobs; directories older than 24 hours are cleaned on startup.
- `server/gpu-ocr.log`, `server/gpu-images.log`: model-worker logs.
- Downloaded model directories and your `.env` stay local and are ignored by Git.

Run the launcher under your own process supervisor if it should start after a reboot.
Stopping the API also stops its model workers; a Linux parent-death signal handles
unexpected API process exits. The app does not provide offline OCR on the iPhone.
