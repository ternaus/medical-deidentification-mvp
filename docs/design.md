# Medical Document De-identification MVP - Design Document

## The decision in one page

Develop the product in two stages.

The first stage is an authenticated web application hosted in Google Cloud Platform (GCP). The application uses only managed, pay-for-use services: [Cloud Run](https://cloud.google.com/run/pricing), [Cloud Storage](https://cloud.google.com/storage/pricing), [Firestore](https://cloud.google.com/firestore/pricing), [Cloud Tasks](https://cloud.google.com/tasks/pricing), [Artifact Registry](https://cloud.google.com/artifact-registry/pricing), and [Identity-Aware Proxy (IAP)](https://cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run). It has no VM, Kubernetes cluster, GPU, Cloud SQL instance, Redis instance, VPC connector, or external load balancer.

Kolya opens the IAP-protected application from a browser on his Windows computer, uploads a document, sees a processing spinner, and then receives the anonymized result. The result page contains a large multi-line `TextArea` for feedback. When Kolya submits it, the application immediately saves the message with the processing session. Vladimir uses the saved feedback to reproduce problems, improve the pipeline, and deploy the next version to the same private service.

The second stage is an installed Windows application. The installer contains the selected OCR and local LLM and starts every required component for Kolya. He does not install Python, Docker, model runtimes, or dependencies and does not use a command line.

The document pipeline and upload-to-result interface serve both stages. In GCP, the backend runs as a private service. On Windows, a launcher starts the backend and opens the interface locally. Model and storage implementations remain replaceable so the web prototype does not create a cloud dependency in the Windows release. Feedback transport for the Windows application is a later decision.

Model selection is CPU-first and constrained by Kolya's computer from the beginning. Local LLM inference is required. The project does not require a GPU and considers a GPU path only after the CPU candidates have been measured and the target computer's GPU has been identified.

The output is intended for a separate external LLM. The application may therefore rebuild every text block with a bundled Cyrillic-capable font. It preserves medical meaning and reading order. Exact fonts, spacing, and page geometry are outside the output contract.

## The target Windows computer sets the model budget

The supplied Windows system-information snapshot records:

| Property | Observed value |
| --- | --- |
| Operating system | Windows 11 Pro, x64 |
| OS build | 22635 |
| Processor | Intel Core i5-750 at 2.67 GHz |
| CPU capacity | 4 cores and 4 logical processors |
| Installed physical memory | 6.00 GB |
| Available physical memory in the snapshot | 2.31 GB |
| Firmware mode | Legacy BIOS |
| GPU and video memory | Not shown in the supplied snapshot |
| Free disk space | Not shown in the supplied snapshot |

This is the compatibility floor for the pilot. The Windows application must not assume AVX, AVX2, a supported GPU, or more available memory until a direct probe confirms those capabilities.

The initial runtime budget is:

- x64 CPU inference with no mandatory GPU runtime;
- one document page processed at a time;
- a quantized local LLM that analyses OCR text;
- OCR and LLM models loaded sequentially when simultaneous residency exceeds the memory budget;
- a measured peak working set that leaves Windows responsive on the target computer; and
- no instruction-set requirement beyond what the target computer passes in an early compatibility test.

The project measures available memory after a clean Windows start before setting a numeric memory limit. The maximum acceptable processing time per page also remains a pilot decision. Both limits must be recorded before selecting the final models.

## Why the web stage comes first

The main unknowns are the clinician's workflow and model behavior on the supplied documents. A web deployment lets Kolya try each iteration without installing development software or receiving a new Windows build.

The current corpus contains source documents but no separate annotations that identify every fragment that must be replaced or retained. The team creates those annotations from the current samples and from failures that Kolya reports. A model comparison without these annotations cannot measure missed identifiers or incorrect replacements.

The web stage answers three questions:

1. Can Kolya upload a document, wait for a result, and report a problem without extra steps?
2. Which OCR and local-LLM combinations produce correct anonymized text?
3. Which successful combinations can run within the Windows computer's CPU, memory, and instruction-set limits?

## Current pilot corpus

The observed corpus contains:

- ten JPEG scans at 2409 x 3436 pixels and 300 DPI;
- one two-page image-only PDF; and
- one one-page PDF with an extractable text layer.

The first release therefore supports `.jpg`, `.jpeg`, `.png`, and multi-page PDF input. It must handle both scanned PDFs and PDFs with text layers.

The current files are source examples. The team annotates them outside the user interface and splits the annotations into configuration examples and previously unused evaluation examples. Reported failures become regression examples after protected data has been handled under the agreed data policy.

## Product boundary

The application accepts a scanned medical document, identifies and replaces personal identifiers, and produces a reconstructed de-identified copy. Kolya uploads one document, waits for processing, downloads the result, and may then submit only that copy to an external LLM. The result page gives him one place to describe any problem in his own words.

The product helps a clinician find and remove identifiers. It does not certify that a document is legally anonymous, replace institutional policy, or make the export decision for the clinician.

Uploading original medical documents to GCP requires explicit authorization for that data flow and an agreed retention policy. Until the decision is recorded, the cloud stage uses synthetic or previously de-identified documents.

## Terms used in this document

- **Source document** - an image or PDF that requires de-identification.
- **Personal identifier** - information that can identify a patient directly or in combination with other information.
- **OCR** - optical character recognition that extracts text and page coordinates from a scan.
- **Local LLM** - a quantized language model that runs inside the controlled application backend. It reads OCR text, identifies personal data, and returns anonymized text blocks with a structured list of replacements. The Windows application packages the same model for on-device inference.
- **External AI service** - a model or service outside the controlled application backend. It may receive the downloaded de-identified copy. It does not receive the source document, unmodified OCR output, application state, or change log.
- **De-identified copy** - a reconstructed document assembled from anonymized OCR blocks. Identifiers are replaced while medical content and reading order are retained.
- **Processing session** - the authenticated upload, its temporary working data, result, and change log.
- **Feedback record** - a persistent message submitted through the result page's multi-line `TextArea` and linked to one processing session.
- **Change log** - a record of every automatic transformation. It may itself contain personal data.

## The clinician's workflow

```text
Sign in and select an image or PDF
        |
        v
Show a processing spinner while the application works
        |
        v
OCR extracts text blocks
        |
        v
Local LLM identifies personal data and anonymizes the text blocks
        |
        v
Reconstruct the document
        |
        v
Show and download the anonymized result
        |
        v
Kolya writes feedback in a large `TextArea`; the application saves it with the processing session
```

The application must make the following path usable without a command line:

1. Sign in.
2. Select one source document.
3. Wait while the application processes it.
4. View and download the reconstructed document.
5. Write feedback in the large multi-line `TextArea` if anything is wrong.

The application never alters the original file.

## Inputs and outputs

### Inputs

The MVP accepts `.jpg`, `.jpeg`, `.png`, and PDF files. It processes every PDF page. It may use an existing PDF text layer as an OCR input, but it does not trust that layer as the final source of page coordinates or redaction.

The MVP excludes other document formats until the pilot shows a concrete need. It does not ingest CSV exports in this release.

### Outputs

For each processed document, the application creates:

1. A reconstructed de-identified document assembled from anonymized OCR blocks and retained non-text clinical content.
2. A separate change log.
3. A result page with a large multi-line `TextArea` for feedback.

When Kolya submits the form, the application creates a persistent feedback record. It stores the feedback text, authenticated user ID, processing-session ID, result ID, server receipt time, and OCR, LLM, prompt, and application versions. The application confirms submission only after the record has been written. If saving fails, it tells Kolya that the feedback was not saved.

The change log records, at minimum:

- source filename;
- page number;
- field or visual region;
- identifier category;
- source fragment;
- replacement or omission action;
- confidence level;
- OCR, LLM, prompt, and application versions; and
- processing time.

The change log is protected data. Application and infrastructure logs must not contain its source fragments, document contents, OCR output, or detected identifiers.

## Personal identifiers the MVP must handle

The MVP must detect and hide or replace the following categories when they appear in the pilot corpus.

| Category | Required examples |
| --- | --- |
| Patient name | Full name; surname with initials; surname and given name; variants in capitalization, spacing, and, where feasible, grammatical case. |
| Date of birth | Common numeric and written date forms. Replace it with the patient's exact age on the document or visit date. |
| Contact data | Phone numbers, email addresses, home address, registration address, actual residence address, and postal code. |
| Government and insurance identifiers | SNILS, OMS/DMS policy number, passport details, INN, and other document identifiers. |
| Medical identifiers | Medical-chart number, medical-history number, internal patient ID, barcode or other patient identifier, and an appointment-ticket number when it can identify the patient. |
| Other potentially identifying information | Workplace, job title, military-unit number, department number, unique address information, names of relatives or legal representatives, and other fragments that can directly identify the patient. |

When the document date is unavailable, the application asks the clinician for it before replacing a date of birth with an age. It must not calculate an age against an arbitrary date.

The application must not automatically delete every date, surname, number, or place name. A surgery date, treating physician's name, laboratory test number, or institution name can be clinically relevant and non-identifying in context. Kolya uses the feedback form to report an incorrect decision.

## OCR and local-LLM selection produces the Windows payload

OCR and local-LLM inference use explicit interfaces so candidate combinations can be compared on the same annotated documents. The Windows payload is selected after the GCP comparison and target-computer benchmark.

The baseline pipeline contains:

1. **CPU OCR** that returns text, confidence, and page coordinates for Russian medical documents.
2. **A quantized local LLM** that identifies personal data and returns anonymized text blocks plus a structured list of replacements.
3. **Document reconstruction** that validates the returned structure, calculates exact age when required, and renders the anonymized blocks.

The LLM receives bounded chunks of OCR text with stable fragment identifiers. It returns schema-constrained JSON containing each anonymized block and the identifiers it replaced. The application validates that every text change is represented in that replacement list, maps the blocks back to their page positions, and reconstructs the document. A failed validation stops export and records a content-free diagnostic event.

The OCR and LLM do not need to remain in memory together. The pipeline may finish OCR for one page, persist its positioned fragments, release the OCR model, load the LLM, and then process the text. This sequence trades processing time for a lower memory peak on the 6 GB target computer.

The first probe uses short bounded context, constrained output, and Qwen3's non-thinking mode. Longer context or thinking mode requires a measured quality improvement because both increase work on the target CPU.

### Initial OCR feasibility candidate

The first Windows compatibility probe uses Tesseract 5 with the official Russian [`tessdata_fast`](https://github.com/tesseract-ocr/tessdata_fast) model. The project describes these integer models as a speed-and-accuracy compromise for Tesseract 4 and 5. This candidate establishes the low-resource OCR floor; it still has to recover the annotated text and coordinates from the pilot scans. A stronger OCR candidate is added only for observed failures that Tesseract cannot meet.

### Initial local-LLM feasibility candidates

The first target-computer probe compares two multilingual Qwen3 GGUF candidates through a CPU-only `llama.cpp` runtime:

| Candidate | Quantized model file | Role in the probe |
| --- | ---: | --- |
| [Qwen3 0.6B Q8_0](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/tree/main) | 639 MB | Establish the smallest model that clearly fits; reject it if identifier recall or Russian instruction following is insufficient. |
| [Qwen3 1.7B Q4_K_M](https://huggingface.co/ggml-org/Qwen3-1.7B-GGUF/tree/main) | 1.28 GB | Test whether the larger model improves identifier detection while Windows remains responsive. |

[Qwen3 lists Russian among its supported languages](https://qwenlm.github.io/blog/qwen3/). File size proves only that model weights fit on disk and can plausibly fit in memory. The probe must still measure runtime overhead, context memory, speed, and detection quality.

The target CPU's instruction-set support remains a packaging constraint. [`llama.cpp` exposes separate build options](https://github.com/ggml-org/llama.cpp/blob/master/ggml/CMakeLists.txt) for SSE4.2, AVX, AVX2, FMA, and related extensions. The Windows probe uses a CPU build that disables every unverified instruction set. The final installer pins the runtime build, model file, configuration, and hashes that pass on Kolya's computer.

Every candidate receives four gates:

1. **Detection quality** - measure false negatives and false positives on held-out annotations.
2. **Export correctness** - every identifier in the reference annotation is absent or replaced in reconstructed text and any retained non-text content.
3. **Target compatibility** - the packaged runtime starts on Kolya's Windows computer without unsupported-instruction errors.
4. **Target performance** - record installation size, cold start, wall time per page, and peak working memory on that computer.

The final Windows installer contains the smallest OCR and local-LLM combination that passes all four gates. GCP performance alone cannot select the Windows models.

## CPU-first GCP experiments

The GCP stage starts without a GPU. Candidate OCR and LLM combinations run on a CPU service and process one page at a time. Once the Windows memory limit is measured, the experiment applies that limit and records the same quality and performance fields used by the Windows benchmark.

A GCP CPU cannot reproduce the age, instruction set, or exact single-core speed of the target processor. GCP measurements rank candidates and expose excessive memory use. Only a target-computer test proves Windows compatibility. The two strongest candidates must run in an early one-click Windows benchmark before the team finishes the desktop packaging.

A GPU experiment requires all of the following:

1. The target computer's GPU model and video memory have been recorded.
2. CPU candidates miss an agreed processing-time or quality target.
3. Profiling shows that model inference is the limiting step.
4. A compatible GPU runtime can be included without making installation or support unreliable.

Until those conditions are met, the plan assumes CPU inference in GCP and Windows.

## Saved TextArea feedback drives improvements

After processing, the application shows the reconstructed document and a large multi-line `TextArea`. The `TextArea` asks one question: “What is wrong or missing?” It gives Kolya enough visible space to describe a problem in detail. Kolya can download the result and submit feedback from the same page.

The application saves feedback synchronously. A submission creates one persistent record linked to the authenticated user and processing session. It is not kept only in the browser, a transient job queue, application logs, email, or chat. The result page shows a receipt after saving succeeds and a clear error after saving fails.

If Kolya reports missing personal data, damaged medical text, an OCR error, or an inconvenient screen, Vladimir opens the linked session through authorized access. The team reproduces the failure, adds an annotation or regression example, improves the OCR, LLM prompt, model, validation, reconstruction, or interface, and deploys the next version.

Feedback is protected data. It uses the same authorization, encryption, access logging, and retention policy as the processing session. The first MVP needs persistent storage and maintainer access to feedback records. It does not need a separate feedback-management interface.

## Export rebuilds content for an external LLM

The application creates a new document from the anonymized OCR blocks returned by the local LLM. Each output block uses a bundled font that supports Cyrillic. The output preserves the medical text and reading order. It may use different line breaks, spacing, block sizes, and page breaks from the source.

The LLM anonymizes each block through targeted replacements and returns every replacement in structured form. It must not paraphrase the remaining medical text. Application code calculates exact age from a detected date of birth and the document or visit date. Other identifiers use an agreed replacement label or omission. Every replacement appears in the change log.

The reconstructed document contains no source text layer, annotations, form values, attachments, document metadata, or source pixels from text regions. This rule prevents a covered or visually replaced identifier from remaining extractable. The result page gives Kolya a direct way to report a clinically meaningful OCR or anonymization error.

Clinically relevant non-text regions, such as ECG traces or plots, may be copied into the reconstructed document and remain visible in the result. The application excludes or sanitizes barcodes, QR codes, signatures, stamps, photographs, and other non-text regions that can identify the patient.

The output must remain readable by the target external LLM. Exact reproduction of the source font and layout is not required. Tables, headings, and reading order are preserved only to the extent needed to keep clinical meaning unambiguous.

## Cheap managed GCP deployment

The pilot has one user and processes one document at a time. The service scales to zero between requests. This removes the fixed cost of an always-running VM while retaining a durable session and feedback record.

```text
Kolya's Google account
        |
        v
IAP-protected Cloud Run web service
        |
        +--> Firestore: sessions, statuses, change logs, feedback
        |
        +--> Cloud Storage: private source and result objects
        |
        v
Cloud Tasks
        |
        v
Private Cloud Run CPU worker: OCR -> local LLM -> reconstruction
        |
        +--> Cloud Storage result + Firestore status
```

| GCP resource | Responsibility | Cost and access control |
| --- | --- | --- |
| Cloud Run web service | Serves the upload, spinner, result, download, and feedback pages. Creates sessions, processing tasks, and user-requested session deletion. | IAP is enabled directly on Cloud Run. Only the approved Google accounts can open it. Set minimum instances to zero. |
| Cloud Run worker service | Runs CPU OCR, the local LLM, reconstruction, and temporary-working-data cleanup. | Not reachable by browser users. Cloud Tasks invokes it with a dedicated service account. Set maximum instances and concurrency to one so only one document consumes CPU and memory. Set minimum instances to zero. |
| Cloud Tasks | Starts one worker invocation after each completed upload. | The browser can disconnect or reload while the task continues. The first one million operations per month are currently free. |
| Cloud Storage | Holds private source pages, reconstructed results, and no application logs. | Use one Standard-class bucket in the selected GCP region. The browser receives a short-lived [signed upload or download URL](https://cloud.google.com/storage/docs/access-control/signed-urls) only after IAP authorizes the session. The bucket has no public listing or public object access. |
| Firestore in Native mode | Stores processing-session metadata, result status, change-log metadata, and feedback records. | Use the default database. It avoids the always-running cost of Cloud SQL and keeps feedback attached to its session. |
| Artifact Registry | Stores the Cloud Run container image, including the selected CPU runtime and model file. | Keep one current image and delete superseded images after a verified rollout. |

IAP directly on Cloud Run protects the service's `run.app` endpoint and avoids the load balancer that an older IAP configuration required. The allowlist is limited to Kolya's and the maintainer's approved Google accounts. The worker runs behind service-to-service IAM, not IAP, because no browser user should invoke it directly.

The browser first asks the web service for an upload session. After the private bucket receives the file, the web service creates a Cloud Task. The worker writes its status to Firestore. The browser polls the IAP-protected session endpoint while showing the spinner, then receives a short-lived download URL after the result is ready. A signed URL is an opaque, temporary capability; the application must not place it in logs, feedback records, email, chat, or GitHub. Feedback submitted from the `TextArea` is written to Firestore before the success receipt appears.

The pilot begins with a USD 10 monthly Cloud Billing budget and alerts at 50%, 90%, and 100%. These alerts do not automatically stop usage or charges, so the maintainer must act on them. It does not use Cloud Run minimum instances. The team reviews actual CPU seconds, stored GiB-days, and request counts after the first pilot sessions before changing the budget or worker resources.

[Cloud Run request-based billing](https://cloud.google.com/run/pricing) includes a monthly free tier for CPU, RAM, and two million requests. [Cloud Storage's Always Free quota](https://cloud.google.com/storage/pricing) applies only in selected US regions, so the project chooses its region for approved medical-data residency first and treats any free quota as a bonus, not as a reason to move data.

## Data boundary during the web stage

Before the GCP application receives original medical documents, the project must record who authorizes this data flow and how long each artifact remains in GCP.

Every browser-visible route, API route, processing session, result, change log, and feedback record requires IAP authentication. The web service allowlist contains only approved Google accounts. The worker accepts only its Cloud Tasks service account. The service has no public document URLs or public signup.

Using original documents in the cloud also requires:

- authenticated access limited to approved users;
- HTTPS for every browser request;
- encryption at rest for stored working data;
- no document content, OCR text, identifiers, or source fragments in infrastructure logs or telemetry;
- a defined deletion rule for uploads, rendered pages, model inputs, session state, outputs, change logs, and feedback records, plus a short expiration rule for signed URLs;
- a user-visible way to delete a working session; and
- verification that deleted working data is no longer available through the application.

The application must not send source documents or derived protected data to an external OCR API, external LLM, analytics service, or developer tool. Software diagnostics use content-free events only. After receiving the result, Kolya may manually submit the reconstructed de-identified copy to an external LLM; automatic transfer remains outside the MVP.

## Smallest architecture that supports both stages

| Component | GCP web stage | Windows stage |
| --- | --- | --- |
| Upload and result interface | IAP-protected Cloud Run web service in Kolya's browser. | Uses the same built interface in a browser or lightweight system web view. |
| Processing coordinator | Cloud Tasks starts one private worker request per uploaded document. | Runs each document sequentially in the local backend. |
| Import and rendering | Private Cloud Storage plus a private Cloud Run worker process images and PDFs. | Processes files selected from the local filesystem. |
| OCR and LLM | The private worker compares replaceable CPU combinations. | Runs the selected packaged CPU models sequentially when required by memory. |
| Reconstruction and export | The worker rebuilds a downloadable document from anonymized OCR blocks. | Writes the same reconstructed output chosen by Kolya. |
| Sessions and feedback | Firestore persists status, feedback, and session links. | Outside the initial Windows package until feedback transport is designed. |
| Working-data lifecycle | The web service deletes a user-requested session's Cloud Storage objects and Firestore records; the worker cleans temporary working data. | Deletes temporary local session data. |

The first version supports one pilot user. It does not need a mobile client, public signup, organization management, high-volume job queue, or Electron runtime.

## Delivery sequence

### 1. Build the authenticated upload, result, and feedback loop

Deploy an IAP-protected Cloud Run web service, private Cloud Storage bucket, Firestore database, Cloud Tasks queue, and one private Cloud Run worker. Require sign-in, import every current sample format, show a processing spinner, display the reconstructed result, and export it using a bundled font. Add the large multi-line `TextArea` and persistent Firestore feedback record. This slice tests the complete user workflow.

### 2. Establish the cloud data boundary

Record whether original documents may enter the selected GCP project. Choose the IAP Google-account allowlist, GCP region, and retention period. Use synthetic or previously de-identified files until this gate passes.

### 3. Compare CPU model candidates in GCP

Run OCR and local-LLM candidates on team-annotated documents. Measure quality, wall time per page, and peak memory under the Windows memory budget.

### 4. Run an early one-click benchmark on Kolya's computer

Package the two strongest model combinations in a temporary benchmark executable. It processes representative non-sensitive test pages and reports compatibility, cold start, wall time, and memory. This throwaway executable answers feasibility only and is deleted after the measurement.

### 5. Select the Windows models

Choose the smallest OCR and local-LLM combination that passes quality, export, compatibility, and target-performance gates. Freeze its model files, runtime versions, and hashes as the Windows payload.

### 6. Package the Windows application

Bundle the selected models, backend, interface, and launcher into an installer. Kolya installs and starts it like a normal application; every internal service starts and stops automatically.

## Acceptance criteria for the web pilot

The web stage is ready when:

1. Kolya can complete the full workflow from his current Windows browser without development software.
2. An unauthenticated visitor cannot access the IAP-protected web service, sessions, previews, outputs, change logs, or feedback records. A browser user cannot invoke the worker directly.
3. The application opens all agreed image formats and every page of the pilot PDFs.
4. OCR returns text blocks, the local LLM returns anonymized blocks, and the application reconstructs the document.
5. Kolya sees a processing spinner until a result or safe failure state is ready, then sees the reconstructed result.
6. The reconstructed output preserves medical text and reading order while replacing personal identifiers.
7. The output contains no recoverable source text layer, source pixels from text regions, or identifying non-text region selected for removal.
8. The target external LLM can read the reconstructed output format.
9. The result page provides a large multi-line `TextArea` and stores submitted feedback in Firestore before confirming success. Each record links to the authenticated user, processing session, result, and pipeline versions.
10. An authorized maintainer can retrieve the saved feedback and linked processing session.
11. A reported failure can be reproduced, added to the evaluation corpus, fixed, and deployed without changing Kolya's URL or setup.
12. Candidate comparisons report false negatives, incorrect replacements, OCR failures, wall time per page, and peak memory.
13. The two strongest CPU candidates are identified for the Windows feasibility probe.
14. The worker has zero minimum instances, one maximum instance, and one processing request at a time.

## Acceptance criteria for the Windows pilot

The Windows application is ready when:

1. A single installer sets up the application without Python, Docker, model downloads, or command-line work.
2. The application starts on Kolya's computer and does not execute unsupported CPU instructions.
3. The selected models remain within the agreed working-memory and processing-time limits.
4. It identifies the required identifiers represented in held-out annotations and returns anonymized text blocks without altering retained medical text.
5. Kolya sees the same upload, processing, and result workflow used in the web pilot.
6. The application exports a de-identified copy and separate change log, then removes temporary working data.

## Explicitly outside the MVP

- Requiring Kolya to configure or start development infrastructure.
- A mandatory GPU runtime.
- A local vision-language model that consumes full page images; the baseline LLM analyses OCR text.
- Mobile application support.
- CSV ingestion or a universal tabular import format.
- Support for document formats absent from the pilot corpus.
- Batch processing of thousands of documents.
- Public signup, multi-organization administration, or general SaaS scaling.
- Automatic transfer to an external LLM or OCR service.
- A claim of universal coverage across medical-document layouts.
- Pixel-perfect reproduction of source fonts, spacing, or page geometry.

## Decisions and measurements still needed

1. The target computer's GPU model, video memory, and free disk space.
2. Direct confirmation of supported CPU instruction sets on the target computer.
3. Whether original medical documents may be uploaded to the selected GCP project and who authorizes that data flow.
4. The GCP region and server-side retention period.
5. The initial ground-truth annotations for configuration and held-out evaluation.
6. The output format accepted by the target external LLM: reconstructed PDF, plain text, or both.
7. The maximum acceptable processing time for a representative page or document.
8. The CPU OCR and local LLM that pass the measured quality, compatibility, time, and memory gates.
9. The retention period for feedback records and whether deleting a processing session also deletes its feedback.
10. The Google accounts included in the IAP allowlist before the first upload of original medical documents.

These decisions select the Windows payload without changing the web-first feedback loop or the CPU-first compute policy.
