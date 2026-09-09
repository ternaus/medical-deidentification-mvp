# Medical Deid

Medical Deid is a local-first application for processing PDFs and document images. The desktop application is a Tauri window with a packaged Python sidecar: it does not start a localhost server or require Python, Node.js, Docker, or a terminal from the user.

At first launch, choose the default light Qwen3 4B profile or an optional larger profile. The app downloads the selected Qwen, Surya OCR files, and the matching local inference runtime, shows progress, verifies SHA-256 checksums, then enables document processing. Apple Silicon uses Metal. Windows uses CUDA when an NVIDIA driver is present and otherwise uses the CPU runtime.

The browser adapter is for local development. Do not deploy original medical documents remotely until access control, jurisdiction, storage retention, and deletion have been decided.

Read the step-by-step product and delivery contract in [docs/greenfield-desktop-delivery-plan.md](docs/greenfield-desktop-delivery-plan.md).
