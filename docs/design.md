# Medical Document De-identification MVP — Design Document

## The decision in one page

Build a local Windows application for a pilot clinician. The application accepts a scanned medical document, identifies personal identifiers on the scan, produces a de-identified copy, and saves a separate local record of what it changed. The clinician reviews uncertain regions before export.

The MVP processes images (`.jpg`, `.jpeg`, and `.png`). It processes scanned PDFs only if they are present in the pilot corpus. It does not process CSV files, provide a mobile application, or send source documents to cloud OCR, an external LLM, or developer infrastructure.

The input scan, OCR text, coordinates, temporary working data, and change log remain on the clinician's computer. Only a clinician-reviewed de-identified result may later be given to an external LLM, outside this application.

The pilot runs on Kolya's Windows computer. The exact Windows version, system architecture, CPU, RAM, GPU availability, and installation permissions must be recorded before choosing the local OCR and language-model runtimes. Until then, the MVP promises compatibility with that pilot machine only, not with Windows computers in general.

## Why this product exists

Medical documents often need analysis, summarisation, or preparation for teaching materials. External AI services can help with those tasks, but raw documents may contain patient identifiers. The application reduces this exposure by creating a reviewed de-identified copy before the document leaves the clinician's device.

The product helps a clinician find and remove identifiers. It does not certify that a document is legally anonymous, replace institutional policy, or make the export decision for the clinician.

## Terms used in this document

- **Source scan** — an image or scanned PDF of a medical document that requires de-identification.
- **Personal identifier** — information that can identify a patient directly or in combination with other information.
- **Local processing** — processing performed on the clinician's computer. The source scan, OCR output, and change log do not leave that computer.
- **OCR** — optical character recognition: extracting text and its location from a scan.
- **Local LLM** — a language model packaged with the application and run on the clinician's computer. It may inspect source text locally to help identify identifiers.
- **External LLM** — a model or service outside the clinician's computer. It never receives the source scan, OCR text, or change log.
- **De-identified copy** — a new document in which selected identifiers are visually hidden or replaced while the medical content is retained.
- **Change log** — a separate local record of every automatic or manual transformation. It may itself contain personal data.
- **Uncertain region** — a region that may contain a personal identifier and requires clinician review.

## The pilot user and corpus define the first release

The primary user is a clinician or medical researcher without programming skills. The first pilot is conducted by Kolya on his Windows computer.

Kolya supplies a small, varied corpus of medical documents. Every example has two artifacts:

1. The original scan or image.
2. A separate annotation or marked copy that says what must be hidden and what must remain visible.

Some examples are used to configure and tune the MVP. Different, previously unused scans are used to evaluate it. Laboratory forms do not have a universal layout, so the MVP begins with the forms in this corpus and is assessed on new variants rather than assuming fixed coordinates or standard field names.

## The clinician's workflow

```text
Source scan or scanned PDF
        |
        v
Local OCR with text coordinates
        |
        v
Local identifier detection and rendering of a new copy
        |
        +--> local change log
        |
        v
Clinician reviews uncertain or edited regions
        |
        v
Export reviewed de-identified copy
        |
        v
Optional manual use of an external LLM
```

The application must make the following path usable without a command line:

1. Select one source document.
2. Run de-identification.
3. Inspect the de-identified copy with identified regions shown in context.
4. Confirm, reject, or manually add a region when needed.
5. Export the de-identified copy and its local change log.

The original file remains unchanged. The application creates a separate output copy.

## Inputs and outputs

### Inputs

Required image formats are `.jpg`, `.jpeg`, and `.png`. Multi-page scanned PDF support is included only when the pilot corpus contains scanned PDFs; each page is rendered and processed as an image.

The MVP excludes other scan formats until the pilot shows a concrete need. It does not ingest CSV exports in this release.

### Outputs

For each processed document, the application creates:

1. A de-identified image or scanned PDF with selected regions hidden or replaced.
2. A separate local change log.
3. A review list of uncertain regions, linked to their page and location on the scan.

The change log records, at minimum:

- source filename;
- page number;
- field or visual region;
- identifier category;
- source fragment;
- replacement or masking action;
- confidence level;
- whether the action was automatic or clinician-made; and
- processing time.

Because the log can contain source fragments, it is protected data. The application must keep it local and must not include it in technical telemetry or external requests.

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

When the document date is unavailable, the application asks the clinician for it before replacing a date of birth with an age. It must not silently calculate an age against an arbitrary date.

The application must not automatically delete every date, surname, number, or place name. A surgery date, treating physician's name, laboratory test number, or institution name can be clinically relevant and non-identifying in context. Ambiguous candidates are shown for review.

## How detection combines rules and a local LLM

The detection pipeline has two complementary stages:

1. **Deterministic detectors** find predictable patterns and field labels, such as phone numbers, email addresses, SNILS, policy numbers, labelled dates of birth, and common patient-number formats.
2. **A local LLM** adds context for free text and less regular identifiers, such as names in prose, workplace references, or a number whose meaning depends on nearby text.

Both stages operate only on the clinician's computer. The OCR result must retain a mapping from each text fragment to its page coordinates so the application can highlight, mask, and review the corresponding area on the original scan.

The product requirement is the observable result: relevant identifiers are found, rendered on the copy, and reviewable. The number of detection passes, retries, or re-scans is an implementation detail and is intentionally outside this design document.

## Confidence and clinician review

Each candidate receives one of three states:

- **High confidence** — the application masks or replaces the candidate automatically and records the action. Examples include a phone number, email address, or a date following a clear "date of birth" label.
- **Needs review** — the application proposes a transformation and shows it to the clinician. Examples include a surname with initials in free text or a number that could be either a patient ID or a laboratory code.
- **Informational** — the application highlights a weak candidate without altering the document until the clinician confirms it.

The clinician can confirm a proposed region, restore an incorrect detection, or add a missed region. Export requires a review step, even when the clinician accepts all automatic transformations.

## How the visual transformation works

The application creates a new rendered copy. For every confirmed identifier, it overlays a mask or a replacement label in the corresponding scan region. The visual layout and clinical content should remain intact as far as the source quality permits.

For date-of-birth fields, the output replaces the birth date with the exact age calculated on the document or visit date. For other identifiers, the replacement can be a standard label such as `[PATIENT]` or a visual redaction. The specific rendering style is an implementation choice, provided that the identifier is not visible in the exported copy and the action is recorded in the change log.

## Privacy boundary and local-data handling

The following data must never be sent to an external LLM, cloud OCR service, developer server, or content telemetry endpoint:

- source scans and scanned PDFs;
- OCR text and coordinates;
- detected identifiers;
- temporary processing artifacts; and
- change logs.

The application may check for software updates without transmitting medical-document content. It should delete temporary processing files after the session and give the clinician a way to remove the local working session. Any external LLM use happens only after the clinician exports and chooses to share a reviewed de-identified copy; that transfer is outside the MVP.

## Windows deployment boundary

The MVP is a standalone local Windows application. The user should be able to select a file, start processing, review the result, and export it without manually configuring a programming environment.

Before implementation selects local OCR and LLM packages, record the pilot machine's:

- Windows version and system architecture;
- CPU model;
- available RAM;
- GPU model and available memory, if any; and
- ability to install or update software.

These facts determine the model size, whether a GPU path is useful, the packaging method, and the performance target. The design does not assume that a GPU exists.

## Smallest architecture that supports the workflow

The MVP consists of six local components:

| Component | Responsibility |
| --- | --- |
| Import and rendering | Opens supported images and, when included in the pilot, renders scanned PDF pages. |
| OCR | Produces text fragments and page coordinates locally. |
| Detection | Combines deterministic detectors with a local LLM to produce identifier candidates and confidence. |
| Transformation | Creates the de-identified visual copy and applies age replacement. |
| Review interface | Shows the original and output context, then accepts clinician confirmations, restorations, and additions. |
| Export and audit log | Writes the de-identified copy and sensitive local change log, then removes temporary data. |

The components communicate through local files or in-process data only. There is no backend service, user account, document-upload API, mobile client, or automatic external-LLM integration in the MVP.

## Acceptance criteria for the pilot

The MVP is ready for pilot use when it can demonstrate all of the following on the held-out pilot scans:

1. It opens the agreed image formats and any scanned PDFs included in the pilot corpus.
2. It runs on Kolya's pilot Windows machine without sending source scans, OCR text, or change logs outside the device.
3. It identifies and visually hides or replaces direct identifiers from the required categories represented in the corpus.
4. It replaces a date of birth with the exact age on the document or visit date, requesting the date when it is missing.
5. It finds patient names across different pilot form layouts.
6. It keeps clinically relevant content and the document's visual structure usable.
7. It exports both a de-identified copy and a separate local change log.
8. It shows uncertain regions on the scan and requires clinician review before export.

The pilot review should record false negatives, false positives, OCR failures, processing time, and any document type that the application cannot process. These observations determine the next iteration; they are not grounds for silently broadening the first release.

## Explicitly outside the MVP

- Mobile application.
- CSV ingestion or a universal tabular import format.
- Cloud OCR, source-document upload, or automatic external-LLM transfer.
- Support for scan formats absent from the pilot corpus.
- Batch processing of thousands of documents.
- A claim of universal compatibility with Windows versions or hardware not represented by the pilot machine.
- Dissertation-specific requirements that do not affect the application workflow.

## Decisions still needed before implementation

1. The pilot machine's Windows version, architecture, CPU, RAM, GPU, and installation permissions.
2. The initial annotated corpus, including whether it contains scanned PDFs and multi-page documents.
3. The output masking style for each identifier category: opaque visual redaction, replacement label, or both.
4. The local OCR and local LLM runtimes that meet the pilot machine's measured limits.
5. The minimum acceptable processing time for a representative pilot scan.

Once these are known, the implementation can choose concrete libraries and models without changing the product boundary above.
