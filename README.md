# Medical Document De-identification MVP

This private repository contains the product and technical design for a medical-document de-identification application. The authenticated GCP pilot uses Cloud Run, Cloud Storage, Firestore, and Cloud Tasks with no virtual machine or GPU. Kolya uploads a document, sees a processing spinner, and then receives the reconstructed de-identified result. The selected OCR and local LLM are then packaged as a Windows application that requires no development setup.

The target Windows computer has a four-core Intel Core i5-750 and 6 GB of RAM. The MVP requires local LLM anonymization, starts with quantized CPU inference, and does not require a GPU.

OCR extracts text blocks. The local LLM identifies personal data and returns anonymized blocks. The application reconstructs the document with a bundled font. The result page includes a large multi-line `TextArea` that immediately saves Kolya's message with the processing session, so the pipeline can be debugged and improved.

The agreed MVP scope is in [the design document](docs/design.md).
