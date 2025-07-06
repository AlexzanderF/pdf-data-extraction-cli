# PDF Data Extractor CLI - User Guide

This guide provides instructions on how to set up and use the PDF Data Extractor CLI tool to extract structured data from PDF documents using Google's Gemini API.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Creating an Extraction Schema](#creating-an-extraction-schema)
- [Usage](#usage)
  - [Command-Line Arguments](#command-line-arguments)
  - [Examples](#examples)
- [Modes of Operation](#modes-of-operation)
  - [File Mode (Default)](#file-mode-default)
  - [Text Mode](#text-mode)
- [Output Format](#output-format)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- Python 3.6+
- Pip (Python package installer)

## Setup

1.  **Clone the Repository:**
    If you haven't already, clone the project repository to your local machine.

2.  **Install Dependencies:**
    Navigate to the project's root directory and install the required Python packages using the `requirements.txt` file.

    ```bash
    pip install -r requirements.txt
    ```

3.  **Set Environment Variable:**
    This tool requires a Google Gemini API key. You must set it as an environment variable named `GEMINI_API_KEY`.

    **macOS / Linux:**
    ```bash
    export GEMINI_API_KEY="YOUR_API_KEY_HERE"
    ```

    **Windows (Command Prompt):**
    ```bash
    set GEMINI_API_KEY="YOUR_API_KEY_HERE"
    ```

    **Windows (PowerShell):**
    ```powershell
    $env:GEMINI_API_KEY="YOUR_API_KEY_HERE"
    ```
    > **Note:** Replace `"YOUR_API_KEY_HERE"` with your actual Gemini API key. To make the variable permanent, add this line to your shell's startup file (e.g., `.bashrc`, `.zshrc`, or your system's environment variable settings).

## Creating an Extraction Schema

The core of the extraction process is the **Extraction Schema**. This is a JSON file you create to tell the AI exactly what information to find and what format to use.

The schema has two main parts:
- `additional_context`: A string providing general guidance or context to the AI about the documents it will process.
- `fields`: An array of objects, where each object defines a specific piece of data to extract.

Each field object contains:
- `key`: The JSON key to use in the output for this piece of data.
- `description`: A clear and detailed description of the information to find. This is the most important part, as the AI relies on it to locate the data.
- `type`: The expected data type (e.g., "string", "number", "boolean", "date").

**Example Schema (`my_schema.json`):**
```json
{
  "additional_context": "Extract key financial and company information from an annual 10-K report.",
  "fields": [
    {
      "key": "company_name",
      "description": "The full legal name of the company filing the report.",
      "type": "string"
    },
    {
      "key": "fiscal_year_end_date",
      "description": "The end date of the fiscal year covered by the report, usually found on the first page. Format as YYYY-MM-DD.",
      "type": "date"
    },
    {
      "key": "total_revenue",
      "description": "The total revenue or sales figure for the most recent fiscal year. It is typically the first line item in the income statement.",
      "type": "number"
    },
    {
      "key": "is_common_stock_listed",
      "description": "A boolean value indicating if the company's common stock is listed on a major exchange like NASDAQ or NYSE.",
      "type": "boolean"
    }
  ]
}
```

## Usage

Run the script from the root of the project directory using `python main.py`.

### Command-Line Arguments

| Argument                | Alias | Description                                                                                               | Default                            |
| ----------------------- | ----- | --------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| `--output <filename>`   | `-o`  | The name of the output JSON file.                                                                         | `extraction_results.json`          |
| `--input-dir <path>`    | `-i`  | Path to the directory containing your PDF files.                                                          | Current directory                  |
| `--schema <filename>`   | `-s`  | The name/path of the extraction schema JSON file.                                                         | `extraction_schema.json`           |
| `--model <model_name>`  | `-m`  | The name of the Gemini model to use.                                                                      | `gemini-1.5-flash-latest`          |
| `--temperature <float>` | `-t`  | Sets the creativity of the model (0.0 for deterministic, 1.0 for creative).                               | `0.0`                              |
| `--text-mode`           |       | A flag to force text extraction mode instead of direct file upload. See [Modes of Operation](#modes-of-operation). | `False`                            |


### Examples

**1. Basic Usage:**
Processes all PDFs in the current directory using `extraction_schema.json` and saves to `extraction_results.json`.

```bash
python main.py
```

**2. Specifying Input and Output:**
Processes PDFs from the `test_pdfs/` directory and saves the results to a file named `my_results.json`.

```bash
python main.py --input-dir test_pdfs/ --output my_results.json
```

**3. Using a Custom Schema:**
Uses a custom schema file named `invoice_schema.json` to process PDFs in the `invoices/` directory.

```bash
python main.py -i invoices/ -s invoice_schema.json -o invoice_data.json
```

**4. Using Text Mode for Large Files:**
Processes a directory of large PDFs using text extraction mode.

```bash
python main.py --input-dir large_reports/ --text-mode
```

## Modes of Operation

The tool can process PDFs in two ways:

### File Mode (Default)
- **How it works:** The entire PDF file is uploaded directly to the Gemini API for analysis.
- **Pros:** More accurate for complex layouts, tables, and documents where context is spread out. It can see the document structure.
- **Cons:** Has a file size limit (currently 50MB).

### Text Mode
- **How it works:** The tool first extracts all plain text from the PDF using the `PyMuPDF` library. This text is then sent to the Gemini API.
- **When to use:**
  - If a PDF file is larger than 50MB.
  - If the direct file upload fails for any reason.
  - For text-heavy documents where layout is not critical.
- **Cons:** May lose contextual information related to layout, tables, and images. Not suitable for scanned/image-based PDFs with no embedded text.

To activate, use the `--text-mode` flag.

## Output Format

The tool generates a single JSON file containing an array of objects. Each object represents the extracted data from one successfully processed PDF file.

In addition to the fields you define in your schema, two metadata fields are automatically added:
- `filename`: The name of the source PDF file.
- `processing_mode`: The mode used for extraction (`file` or `text`).

**Example Output (`extraction_results.json`):**
```json
[
    {
        "company_name": "NVIDIA Corporation",
        "fiscal_year_end_date": "2024-01-28",
        "total_revenue": 60922000000,
        "is_common_stock_listed": true,
        "filename": "nvidia_10-k.pdf",
        "processing_mode": "file"
    },
    {
        "company_name": "Some Other Company",
        "fiscal_year_end_date": null,
        "total_revenue": 12345000,
        "is_common_stock_listed": false,
        "filename": "another_report.pdf",
        "processing_mode": "text"
    }
]
```
> Note: If a piece of information cannot be found in a document, its value will be `null`.

## Troubleshooting

- **Error: `GEMINI_API_KEY` environment variable not found:**
  Ensure you have correctly set the environment variable and that it's available in your current terminal session.

- **Error: Extraction schema file not found:**
  Check that the file name and path provided with the `-s` or `--schema` argument are correct.

- **Error: Invalid JSON in extraction schema file:**
  Your schema file has a syntax error. Use a JSON validator to find and fix it.

- **No PDF files found:**
  Make sure the path provided to `-i` or `--input-dir` is correct and contains `.pdf` files.

- **Error: Failed to decode JSON from LLM response:**
  This can happen if the model's response is not valid JSON. Try running the script again. If the problem persists, consider simplifying your schema's `description` fields or adjusting the model `temperature`. 