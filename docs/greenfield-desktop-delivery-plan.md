# Greenfield Plan: Web, Windows, and macOS Applications

## Greenfield rule

This plan assumes an empty repository. It does not reuse, preserve, migrate, or accommodate any existing frontend, backend, API, database, build system, or deployment structure.

The product requirements drive every choice:

- one interface for the browser, Windows, and macOS;
- no terminal, console window, or manually started server on desktop;
- local OCR and model execution when the machine passes a hardware preflight;
- a separately deployable private web application;
- source documents and derived identifiers remain inside the selected processing boundary;
- Windows x64 and Apple Silicon macOS are the first desktop targets.

## Decision

Build the product with four parts:

1. **React, TypeScript, and Vite** for the shared user interface.
2. **Tauri v2** for the Windows and macOS application shell, native dialogs, lifecycle, installers, and code signing.
3. **A packaged Python worker** for OCR, identifier detection, reconstruction, and export.
4. **A FastAPI web service** for the private browser deployment.

The desktop application does not run a local HTTP server. Tauri starts the Python worker as a hidden sidecar process and communicates with it through newline-delimited JSON messages over stdin/stdout. Closing the application stops the worker.

The web application uses HTTPS because a browser cannot invoke the desktop sidecar. The UI selects one of two thin transports at startup:

- `DesktopTransport` calls typed Tauri commands;
- `WebTransport` calls typed HTTPS endpoints.

Both transports implement the same generated application contract. Business logic lives in the Python core and is not duplicated between transports.

## What the user launches

### Windows

The user downloads `MedicalDeidSetup-<version>-windows-x64.exe`, installs it, and starts `MedicalDeid` from the Start Menu. The installed application contains `MedicalDeid.exe`, the Tauri shell, the compiled interface, and the packaged Python worker.

No Command Prompt or PowerShell window appears. The user never starts Python, Node.js, Docker, an API server, or a model process.

### macOS

The user downloads `MedicalDeid-<version>-macos-arm64.dmg`, drags `MedicalDeid.app` into Applications, and starts it from Finder.

The application contains an arm64 Tauri executable, the compiled interface, and the packaged arm64 Python worker. Terminal does not open.

### Browser

The user opens a private HTTPS URL. The browser loads the same compiled interface and talks to the remote Python web service.

Original medical documents may enter this deployment only after its authorization, region, retention, deletion, and identity-access decisions have been recorded and verified. Until then, the web deployment accepts synthetic or previously de-identified documents only.

## Runtime architecture

### Desktop

```text
MedicalDeid.exe or MedicalDeid.app
        |
        +--> Tauri native window
        |       |
        |       +--> React interface
        |       +--> native open/save dialogs
        |
        +--> Rust command layer
                |
                +--> stdin/stdout JSON protocol
                        |
                        v
                packaged Python worker
                        |
                        +--> OCR
                        +--> identifier detection
                        +--> reconstruction
                        +--> local SQLite session state
                        +--> local source/result/change-log files
```

There is no listening TCP port, localhost URL, firewall rule, or background system service.

### Web

```text
Browser
   |
   v
Static React application
   |
   v
Authenticated HTTPS API
   |
   v
Python web service --> job queue --> Python worker
   |                                    |
   +--> metadata database               +--> OCR/model/reconstruction
   +--> private object storage
```

The desktop worker and web worker call the same Python application core. The web service owns authentication, remote storage, and job orchestration. The desktop shell owns local files and process lifecycle.

## Why Tauri is the desktop shell

Tauri uses WebView2 on Windows and WKWebView on macOS, so it does not bundle a second Chromium runtime. It supports external sidecar binaries, native application bundles, Windows installers, macOS disk images, code signing, and notarization.

Tauri documents Python CLI programs and API servers packaged with PyInstaller as a sidecar use case: <https://v2.tauri.app/develop/sidecar/>. Its process model uses WebView2 on Windows and WKWebView on macOS: <https://v2.tauri.app/concept/process-model/>. Its distribution tooling produces Windows installers and macOS `.app`/`.dmg` artifacts: <https://v2.tauri.app/distribute/>.

## Options considered

| Option | Desktop HTTP server | Shared web UI | Packaging burden | Decision |
| --- | ---: | ---: | --- | --- |
| Tauri plus Python sidecar over stdin/stdout | No | Yes | Rust, web, and Python toolchains | **Selected. It meets every delivery and UX requirement.** |
| Tauri plus Python localhost API | Yes, hidden | Yes | Slightly simpler desktop transport | Reject because greenfield design can avoid an open local port. |
| `pywebview` plus Python backend | Usually yes | Yes | Python-centric | Reject because Tauri provides a clearer sidecar, installer, permission, and signing boundary. |
| Electron plus Python sidecar | No | Yes | Bundled Chromium and Node.js | Reject because the larger shell does not replace the Python worker or model payload. |
| PySide6/Qt | No | No | One Python executable, two independent UIs | Reject because browser and desktop behavior would drift. |
| Flutter | No | Yes | Dart plus Python worker and custom bridge | Reject because it adds another UI ecosystem without removing the worker boundary. |
| Browser/PWA only | Remote HTTPS only | Yes | Lowest packaging burden | Reject because the required `.exe` and macOS application would not exist. |

## The shared application contract

Define the user-visible operations before implementing a transport:

- create a processing session;
- select or upload one PDF, JPG, JPEG, or PNG document;
- receive content-free progress events;
- provide a missing document date when exact age cannot be calculated;
- read the terminal success or safe failure state;
- view and save the reconstructed result;
- view and save the separate change log;
- submit feedback;
- delete a session and its working data;
- inspect application, OCR, model, prompt, and schema versions.

Define requests, responses, progress events, and errors in one JSON Schema package. Generate TypeScript types for the UI and Pydantic models for Python. The Rust command layer passes validated messages and never reimplements medical logic.

`DesktopTransport` maps these operations to Tauri commands. The Rust commands write requests to the worker and emit worker events to the WebView. `WebTransport` maps the same operations to HTTPS endpoints and server-sent events. Transport-specific errors are normalized into the shared error schema before reaching UI components.

## Desktop worker protocol

The Tauri process starts exactly one worker per application instance. The worker reads one JSON object per line from stdin and writes one response or event per line to stdout.

Example message sequence:

```text
Tauri -> worker: initialize(application_data_dir, runtime_mode)
worker -> Tauri: ready(runtime_versions, model_status)
Tauri -> worker: create_session(session_id, source_path)
worker -> Tauri: progress(session_id, stage="ocr")
worker -> Tauri: progress(session_id, stage="de-identification")
worker -> Tauri: completed(session_id, result_path, change_log_path)
Tauri -> worker: shutdown
worker -> Tauri: stopped
```

The protocol follows these rules:

- stdout contains protocol messages only;
- diagnostics go to stderr and never include filenames, OCR text, identifiers, prompts, or document content;
- large documents and PDFs move through application-owned files, not base64 protocol messages;
- each message has a request ID, session ID when applicable, schema version, and bounded payload size;
- malformed, unknown, duplicated, or out-of-order messages fail closed;
- Tauri kills the worker if graceful shutdown exceeds the shutdown deadline;
- a worker crash changes the active session to a safe failure state and exposes no result;
- the desktop application never executes arbitrary worker arguments or shell commands.

On Windows, the Rust launcher uses the no-console subsystem and starts the worker with `CREATE_NO_WINDOW` while retaining its stdin/stdout pipes. A clean Windows VM test verifies that no console flashes during startup, processing, worker restart, shutdown, or uninstall.

## The Python core

The Python core owns only application behavior:

- import and render every input page;
- run OCR and return positioned text blocks;
- detect identifiers with deterministic rules and the selected local model;
- validate every proposed replacement against source OCR text;
- calculate exact age from the document or visit date;
- reconstruct the result without retaining an unsafe source text layer;
- mask identifying barcodes, QR codes, and selected visual regions;
- write the protected change log;
- validate the exported document before reporting success;
- remove temporary working files after success, failure, cancellation, or deletion.

The core receives abstract source, work, and destination paths. It does not import Tauri, HTTP, cloud storage, a database client, or UI code.

Three small adapters call the core:

- the desktop stdio worker;
- the web job worker;
- the fixed-corpus evaluator.

No adapter may alter identifier decisions, replacement validation, export rules, or fail-closed behavior.

## Application and model packages are independent

The desktop installer contains the Tauri shell, interface, packaged Python runtime, OCR/LLM integration code, and native libraries. It does not contain the accepted GGUF weights or OCR model cache.

The current accepted reference model is approximately 17 GB. A one-file executable containing that model would be slow to build, copy, verify, update, and roll back. Smaller models may replace it only after passing the same fixed-corpus leak gate.

The model package contains:

- exact model and OCR files;
- a signed manifest;
- SHA-256 checksums;
- model, OCR, prompt, and schema versions;
- supported operating systems and architectures;
- required CPU instructions and accelerator runtime;
- minimum free disk and available memory;
- the fixed-corpus validation receipt.

The release process signs the canonical manifest with Ed25519. The application contains the corresponding public key; the private signing key remains outside the repository and build artifacts. The application imports the package through a native file picker, verifies the signature and every checksum, and installs it under the operating system's application data directory. It never silently downloads or selects another model.

Application and model versions may change independently. The compatibility manifest states which application schema versions can load each model package.

## Two build profiles

### Interface review

The first artifacts are interface-review builds for Windows x64 and Apple Silicon macOS. They contain approved synthetic before/after fixtures and exercise:

- first launch;
- empty state;
- document selection appearance;
- processing progress;
- missing-document-date prompt;
- before/after comparison;
- result save dialog;
- feedback success and failure;
- session deletion;
- worker crash and safe recovery;
- application close and relaunch.

The review build rejects arbitrary files. The title bar and first screen say `Interface review — synthetic data only`. It cannot be mistaken for a functioning anonymizer.

### Local processing

The production desktop build enables file selection only after a signed model package has been installed and the hardware preflight passes.

The preflight checks:

- operating system and architecture;
- required CPU instructions;
- available memory and free disk;
- model and OCR checksums;
- native runtime loading;
- a short synthetic OCR and inference probe;
- application/model schema compatibility.

A successful interface-review build proves packaging and UX only. It does not prove OCR quality, identifier recall, export safety, or acceptable processing time.

## Runtime and UX budgets

The first implementation uses these budgets:

- show the desktop window within 5 seconds on a supported clean machine;
- keep OCR and model weights unloaded until local processing starts;
- keep the interface responsive while the worker processes a document;
- emit a visible stage transition or heartbeat at least every 2 seconds;
- process one document at a time per application instance;
- cancel or checkpoint the active session before the desktop shutdown deadline;
- stop an idle worker and application within 5 seconds after the user closes the window;
- preserve completed local sessions across an ordinary application restart;
- expose no partially generated result after cancellation, crash, or validation failure.

The document wall-time and peak-memory budgets are recorded per supported hardware profile. A platform/model pair is unsupported until it passes those measured budgets and the fixed-corpus quality gate.

## Data and security boundaries

### Desktop

- Store session data under `%LOCALAPPDATA%/MedicalDeid` on Windows and `~/Library/Application Support/MedicalDeid` on macOS.
- Keep source documents, rendered pages, OCR text, detected identifiers, results, feedback, and change logs on the local machine.
- Give the Tauri shell permission to start only the bundled worker binary with fixed arguments.
- Do not expose the shell plugin directly to arbitrary frontend commands.
- Apply a restrictive content security policy to the WebView.
- Disable external navigation, remote scripts, analytics, crash-upload services, and automatic document transfer.
- Use native dialogs for opening source files and saving results.
- Keep diagnostic logs content-free and rotate them by size.
- Delete temporary session files after every terminal state.

### Web

- Require authenticated HTTPS for every page and API operation.
- Store source and result objects privately.
- Keep worker endpoints unreachable from browser users.
- Use short-lived capabilities for direct object transfer only when the authenticated API created them.
- Define deletion and retention for source files, rendered pages, OCR text, model inputs, results, change logs, feedback, and database records.
- Keep document content and identifiers out of infrastructure logs and telemetry.
- Process original medical documents only after the cloud data gate is approved.

## Greenfield repository layout

```text
apps/
  ui/                         React, TypeScript, Vite, shared components
  desktop/                    Tauri v2 shell and Rust command layer
services/
  web-api/                    authenticated Python HTTPS adapter
  web-worker/                 queued Python processing adapter
packages/
  contract/                   JSON Schema and generated TypeScript/Pydantic types
  python-core/                OCR, de-identification, reconstruction, validation
  desktop-worker/             stdin/stdout Python adapter
  evaluator/                  fixed-corpus and leak-gate runner
packaging/
  models/                     manifest schema; model files remain untracked
tests/
  contract/
  core/
  desktop/
  web/
  packaged/
```

Generated artifacts, source documents, results, local databases, model weights, caches, signing certificates, and notarization credentials never enter Git.

## Implementation sequence

### 1. Freeze the product and message contracts

- Define the supported input formats, session states, progress stages, failure states, result artifacts, change-log fields, and deletion semantics.
- Write JSON Schemas for commands, responses, events, and errors.
- Generate TypeScript and Pydantic types and verify round-trip fixtures.

Completion gate: TypeScript, Rust, and Python reject the same invalid fixtures and accept the same valid fixtures.

### 2. Build the interface-review web application

- Build the complete React interface against a synthetic in-memory transport.
- Implement every required state before connecting OCR or a model.
- Verify responsive layouts on Windows and macOS screen sizes.

Completion gate: the browser completes every interface-review scenario using synthetic data, with no backend process.

### 3. Build the Python core and evaluator

- Implement import, OCR, identifier detection, replacement validation, reconstruction, export validation, and cleanup as one sequential pipeline.
- Build the fixed-corpus evaluator before selecting a production model package.
- Fail closed on proposal mismatch, leaked identifiers, unsafe text layers, and unreadable exports.

Completion gate: the accepted model passes the complete fixed corpus, independent leak searches, and export checks.

### 4. Build the desktop worker protocol

- Package a minimal worker with PyInstaller `onedir` so heavy libraries stay installed between launches instead of unpacking on every start.
- Implement initialize, process, cancel, feedback, delete, and shutdown commands.
- Add protocol fuzz tests, crash tests, duplicate-message tests, and forced-shutdown tests.

Completion gate: the worker never emits non-protocol stdout, never exposes a partial result, and recovers unfinished session state safely after a crash.

### 5. Build the Tauri application

- Integrate the shared interface.
- Start and supervise one worker from Rust.
- Add native open/save dialogs, application data paths, single-instance behavior, and content-free diagnostics.
- Compile interface-review builds with arbitrary file input disabled.

Completion gate: clean Windows x64 and Apple Silicon macOS machines complete every review scenario without a terminal, developer runtime, or visible child process.

### 6. Produce native installers

- Build the Windows worker and Tauri application on Windows x64.
- Build the macOS worker and Tauri application on Apple Silicon macOS.
- Create the Windows setup `.exe`, macOS `.app`, and macOS `.dmg`.
- Record SHA-256 checksums and a release manifest containing the exact source revision and tool versions.

Tauri sidecars are platform-specific external binaries and use target-triple filenames. The official sidecar guide requires one binary per supported target: <https://v2.tauri.app/develop/sidecar/>.

Completion gate: clean-machine install, launch, close, relaunch, upgrade, rollback, and uninstall tests pass on both operating systems.

### 7. Add the signed model package and preflight

- Implement model import and signature/checksum verification.
- Add hardware preflight and the synthetic runtime probe.
- Run full local processing on each declared supported hardware profile.

Completion gate: unsupported machines reject real files before processing; supported machines pass the full corpus and resource budgets.

### 8. Sign and publish desktop releases

- Sign the Windows executable and installer with Authenticode.
- Sign the macOS app with Developer ID, enable hardened runtime, notarize it, and staple the notarization ticket.
- Verify the distributed artifact on clean machines after download.

Tauri's distribution documentation requires code signing and notarization for macOS applications distributed outside the App Store: <https://v2.tauri.app/distribute/>.

Completion gate: the normal double-click installation path is accepted by Windows SmartScreen and macOS Gatekeeper.

### 9. Build the private web deployment

- Implement the HTTPS transport, authentication, metadata storage, object storage, queue, and worker invocation.
- Use the same generated contract and Python core.
- Verify authorization and deletion before enabling original document uploads.

Completion gate: an unauthenticated user cannot reach any session artifact, a browser user cannot invoke the worker directly, and verified deletion removes the agreed remote data.

The cloud provider, region, retention period, identity allowlist, and authorization for original documents require a separate approved deployment plan. This greenfield plan fixes the application boundary and transport contract; it does not select those operational values.

## Verification matrix

| Gate | Browser | Windows x64 | macOS arm64 |
| --- | ---: | ---: | ---: |
| Shared contract tests | Required | Required | Required |
| Interface review scenarios | Required | Required | Required |
| No console or terminal | N/A | Required | Required |
| No local listening port | N/A | Required | Required |
| Worker crash and recovery | Server gate | Required | Required |
| Clean install and uninstall | N/A | Required | Required |
| Application signature | HTTPS deployment | Required | Required |
| Model-package verification | Worker gate | Required | Required |
| Fixed-corpus leak gate | Required | Required | Required |
| Peak memory and wall time | Server profile | Hardware profile | Hardware profile |
| Export text-layer and pixel checks | Required | Required | Required |
| Session deletion | Required | Required | Required |

## Acceptance criteria

The greenfield delivery is complete when:

1. One React source tree produces the browser, Windows, and macOS interfaces.
2. Windows installs through a setup `.exe` and launches without a console window.
3. macOS installs from a `.dmg` and launches without Terminal.
4. Desktop applications open no listening port and communicate with the packaged worker through supervised pipes.
5. Closing the desktop application stops the worker and leaves no child process.
6. Clean machines complete all synthetic interface-review scenarios without Python, Node.js, Rust, Docker, or command-line work.
7. Real file selection remains disabled until a signed model package and hardware preflight pass.
8. Application and model packages update and roll back independently.
9. A platform/model pair is called supported only after fixed-corpus leak checks, export validation, peak-memory measurement, and wall-time measurement pass on that platform.
10. Original documents never enter the private web deployment before its cloud data gate passes.
11. Release artifacts contain no patient documents, OCR text, change logs, databases, model cache, build cache, or credentials.

## Explicit non-goals

- Preserving or migrating any existing repository code.
- A localhost API or manually started desktop server.
- A public web service or public signup.
- Separate React, Windows, and macOS interfaces.
- A one-file executable containing 17 GB of model weights.
- Cross-compiling the final Windows and macOS releases on one operating system.
- Auto-selecting an unvalidated model because it fits available memory.
- Calling an interface-review pass evidence of anonymization quality.
- Sending source documents, OCR text, identifiers, or change logs to external analytics, OCR, or LLM services.
