# Greenfield plan: local web and desktop application

## What the user gets

The same interface works in two ways:

- in a browser during development, through a local FastAPI server;
- as a Windows `.exe` or Apple Silicon macOS `.app`/`.dmg`, without starting a server or opening a terminal.

On the first launch the application says that models are missing. The user chooses a Qwen profile, clicks **Download**, sees the current file and total progress, and cannot submit a document until every downloaded file passes its SHA-256 check. After that they choose a PDF, JPG, JPEG, or PNG, wait for local processing, and save the anonymized PDF.

The desktop application has no listening HTTP port. Tauri starts one hidden Python sidecar and sends it bounded JSON requests over stdin/stdout. The browser uses the HTTP adapter because it cannot call the sidecar.

## Product decisions

| Decision | Choice | Consequence |
| --- | --- | --- |
| First model | Qwen3 4B, Q4_K_M | Default download is about 2.3 GiB and requires 8 GiB RAM. |
| Optional models | Qwen3 8B and 30B-A3B, Q4_K_M | The settings screen can install them later; they need about 4.7/17 GiB for the model and 16/32 GiB RAM. |
| OCR | Surya OCR 2 GGUF plus vision projector | The first selected-profile installation also downloads about 1.4 GiB of OCR files. |
| macOS accelerator | llama.cpp Metal runtime | Apple Silicon uses Metal; this Mac exposes Metal 4 on its M4 Max GPU. |
| Windows accelerator | llama.cpp CUDA runtime when `nvidia-smi` finds an NVIDIA driver | The installer uses CUDA for NVIDIA GPUs; otherwise it installs the CPU runtime. AMD and Intel GPU backends are not in this release. |
| Download integrity | Immutable file URLs, expected size, SHA-256, then atomic rename | A partial or altered file never becomes an enabled model. |
| Document boundary | Local application data directory | Desktop input, OCR, model prompts, SQLite metadata, temporary pages, and result stay on the device. |
| Browser boundary | Localhost development adapter only | Hosting original medical documents remotely requires a separate decision on authentication, region, retention, and deletion. |

Qwen3's official GGUF releases provide the 4B, 8B, and 30B-A3B files used by the catalog: [4B](https://huggingface.co/Qwen/Qwen3-4B-GGUF), [8B](https://huggingface.co/Qwen/Qwen3-8B-GGUF), and [30B-A3B](https://huggingface.co/Qwen/Qwen3-30B-A3B). llama.cpp documents Metal builds on macOS and CUDA builds for NVIDIA platforms in its [build guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md).

## Runtime flow

```text
First launch
  → choose Qwen profile
  → download runtime, OCR, and model with visible byte progress
  → verify hashes and hardware preflight
  → enable document selection

Document
  → native file dialog (desktop) or browser upload (local web)
  → one local processing queue
  → OCR with Surya + local llama.cpp runtime
  → identifier proposals with selected Qwen
  → reconstruct and validate anonymized PDF
  → native save dialog (desktop) or result download (web)
```

The preflight rejects unsupported systems, insufficient RAM/disk, missing OCR/model files, and an unavailable runtime. It deliberately fails closed: an unavailable model cannot produce a partially processed export.

## Repository layout

```text
apps/ui/                         shared React UI
apps/desktop/                    Tauri application and native dialogs
packages/contract/               TypeScript transport contract
packages/python-core/            verified model store and shared logic
packages/desktop-worker/         stdin/stdout sidecar adapter
services/web-api/                local browser adapter
src/medical_deid/                OCR, redaction, reconstruction, validation
```

The desktop worker stores data in `~/Library/Application Support/MedicalDeid` on macOS and `%LOCALAPPDATA%/MedicalDeid` on Windows. Model weights and session artifacts are intentionally untracked.

## Delivery steps and acceptance checks

1. Build the UI and confirm first launch shows the Qwen catalog, accelerator, disk/RAM requirements, and **Download** button.
2. Run the model installation against each supported OS. Confirm the byte counter advances, a failed checksum leaves no usable file, and the selected model persists after restart.
3. Process representative PDF and image documents after installation. Confirm only a validated result becomes downloadable; failed OCR or model output produces no result file.
4. Build native artifacts on each target OS:
   - Apple Silicon macOS: arm64 sidecar, `.app`, and `.dmg`.
   - Windows x64: x64 sidecar and NSIS `.exe` installer.
5. On clean machines, install, launch from Finder/Start Menu, download the default model, process a document, save the result, close, and relaunch. No terminal or manually started server is allowed.

## Explicit limits before public release

- The macOS artifact is unsigned and therefore may trigger Gatekeeper. Signing and notarization are release work, not bypassed by the app.
- Windows needs a native Windows build; macOS cannot produce a trustworthy Windows `.exe` artifact.
- The model downloader is hash-pinned but not yet an Ed25519-signed release manifest.
- A successful startup, installer build, or one document run is not evidence of medical de-identification quality. A fixed evaluation corpus, identifier-recall review, leak checks, and platform performance measurements must gate any clinical or public claim.
