# Medical Deid desktop

This Tauri v2 application runs on Windows x64 and Apple Silicon macOS. It loads
the shared Vite interface and starts `medical-deid-worker` as a hidden sidecar
over newline-delimited JSON on stdin/stdout. The checked-in `binaries/`
directory is intentionally empty. Each native build writes its worker there
with the target triple required by Tauri.

## Build a macOS application

Run these commands from the repository root. The resulting unsigned DMG is at
`apps/desktop/src-tauri/target/release/bundle/dmg/`.

```bash
uv sync --locked --group dev
uv run python scripts/build_desktop_worker.py --target aarch64-apple-darwin --clean
npm ci --prefix apps/ui
npm ci --prefix apps/desktop
npm --prefix apps/ui run build
npm --prefix apps/desktop run tauri build
```

For a Windows x64 installer, run the same commands on Windows and replace the
worker target with `x86_64-pc-windows-msvc`. The first launch downloads the
chosen model and the runtime matching the host: Metal on Apple Silicon, CUDA
for Windows NVIDIA, and CPU otherwise.
