#!/usr/bin/env python3
import os
import json
import argparse
import pymupdf  # PyMuPDF
import google.generativeai as genai
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
import csv
from pathlib import Path

# Check for API key in environment variables first, then fall back to hardcoded value
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
DEFAULT_MODEL = "gemini-2.5-flash-lite-preview-06-17"
DEFAULT_EXTRACT_SCHEMA = "extraction_schema.json" 
DEFAULT_TEMPERATURE = 0.0

# Gemini file upload limits
GEMINI_MAX_FILE_SIZE_MB = 50
GEMINI_MAX_FILE_SIZE_BYTES = GEMINI_MAX_FILE_SIZE_MB * 1024 * 1024

ROLE_MESSAGE_PROMPT = """You are a highly intelligent and extremely precise and accurate at data extraction.
You are an expert at analyzing all sorts of documents and structured or unstructured data.
You will analyze this document and extract structured data according to the provided schema.
Your sole output must be a single, valid JSON object that strictly adheres to the provided schema."""

# Shared instructions for both text and file modes
SHARED_INSTRUCTIONS = """
    ### INSTRUCTIONS
    1.  **Analyze the Schema**: Carefully examine the Extraction Schema provided below. It defines the structure, data types, and descriptions of the information you need to find.
    2.  **Scan the Document**: Read the document text and identify the data points that match the descriptions in the schema `description` field.
    3.  **Populate the JSON**: Construct a JSON object. The keys in your JSON output **must exactly match** the `keys` from the schema.
    4.  **Handle Missing Data**: If the information is not present, use the JSON value `null`.
    5.  **Respect Data Types**: Extract the data in the correct data type specified in the schema `type` field.
    6.  **Final Output**: Your response **must only contain the final JSON object**. Do not include any explanations, conversational text like "Here is the JSON you requested:" or markdown formatting like ```json ... ``` before or after the JSON object.

    ### ADDITIONAL CONTEXT
    {additional_context}

    ### EXTRACTION SCHEMA
    ```json
    {extraction_schema}
    ```
"""

# Text mode specific prompt (adds document text section)
TEXT_MODE_PROMPT = SHARED_INSTRUCTIONS + """

    ### DOCUMENT TEXT
    {document_content}
"""

# File mode prompt (uses only shared instructions)
FILE_MODE_PROMPT = SHARED_INSTRUCTIONS

console = Console()

def format_file_size(size_bytes):
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 / 1024:.1f} MB"

def load_extraction_schema(extraction_schema_file_path):
    """Load extraction schema from external file. Returns parsed schema dict or None if file cannot be read."""
    try:
        with open(extraction_schema_file_path, 'r', encoding='utf-8') as f:
            schema_data = json.load(f)
        return schema_data
    except FileNotFoundError:
        console.print(f"[bold red]Error: Extraction schema file not found: {extraction_schema_file_path}[/bold red]")
        return None
    except json.JSONDecodeError as e:
        console.print(f"[bold red]Error: Invalid JSON in extraction schema file: {e}[/bold red]")
        return None
    except Exception as e:
        console.print(f"[bold red]Error reading extraction schema file: {e}[/bold red]")
        return None

def configure_gemini():
    """Configures the Gemini API with the key from environment variables."""

    if not GEMINI_API_KEY:
        console.print("[bold red]Error: GEMINI_API_KEY environment variable not found.[/bold red]")
        console.print("Please set the environment variable before running the script.")
        return False
    
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        return True
    except Exception as e:
        console.print(f"[bold red]An error occurred during Gemini configuration: {e}[/bold red]")
        return False
    
def process_file(file_path, model, extraction_schema, text_mode=False):
    """
    Processes a file using either direct file upload or extracted text.
    Returns a dictionary with extracted data or None on failure.
    """
    
    filename = os.path.basename(file_path)
    
    additional_context = extraction_schema.get('additional_context', 'No specific context provided.')
    fields_json = json.dumps(extraction_schema.get('fields', []), indent=2)

    try:
        if not text_mode:
            # File Mode: Upload file directly to Gemini
            file_size = os.path.getsize(file_path)
            
            if file_size > GEMINI_MAX_FILE_SIZE_BYTES:
                console.print(f"  [yellow]Warning: File {filename} ({format_file_size(file_size)}) exceeds Gemini's {GEMINI_MAX_FILE_SIZE_MB} MB limit. Falling back to text mode.[/yellow]")
                return None
            
            try:
                uploaded_file = genai.upload_file(file_path)
                
                prompt = FILE_MODE_PROMPT.format(
                    additional_context=additional_context,
                    extraction_schema=fields_json
                )
                
                response = model.generate_content(
                    [prompt, uploaded_file]
                )

                # Clean up the uploaded file
                genai.delete_file(uploaded_file.name)
                
                # Add metadata
                metadata = {
                    'filename': filename,
                    'processing_mode': 'file'
                }
            except Exception as e:
                console.print(f"  [yellow]Warning: File upload failed for {filename}: {e}[/yellow]")
                return None
            
        if text_mode:
            # Text Mode: Extract text using PyMuPDF
            try:
                doc = pymupdf.open(file_path)
            except Exception as e:
                console.print(f"  [red]Error: trying to open PDF - {filename} ({e})[/red]")
                return None

            page_count = doc.page_count
            pdf_text_content = ""

            for page in doc:
                pdf_text_content += page.get_text()
            
            doc.close()

            if not pdf_text_content.strip():
                console.print(f"  [yellow]Skipping image-based or empty PDF: {filename}[/yellow]")
                return None

            prompt = TEXT_MODE_PROMPT.format(
                document_content=pdf_text_content,
                additional_context=additional_context,
                extraction_schema=fields_json
            )
            
            response = model.generate_content(
                prompt
            )
            
            # Add metadata
            metadata = {
                'filename': filename,
                'processing_mode': 'text'
            }
        
        # Clean up potential markdown formatting from the response
        cleaned_response_text = response.text.strip().replace("```json", "").replace("```", "")
        
        # Try to extract JSON from the response if it's wrapped in other text
        try:
            # First, try to parse as-is
            extracted_data = json.loads(cleaned_response_text)
        except json.JSONDecodeError:
            # If that fails, try to find JSON within the response
            import re
            json_match = re.search(r'\{.*\}', cleaned_response_text, re.DOTALL)
            if json_match:
                try:
                    extracted_data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    console.print(f"  [red]Error: Failed to decode JSON from LLM response for {filename}.[/red]")
                    console.print(f"  [dim]LLM raw response: {response.text[:500]}...[/dim]")
                    return None
            else:
                console.print(f"  [red]Error: No valid JSON found in LLM response for {filename}.[/red]")
                console.print(f"  [dim]LLM raw response: {response.text[:500]}...[/dim]")
                return None
        
        # Handle case where LLM returns a list instead of a dictionary
        if isinstance(extracted_data, list):
            if len(extracted_data) > 0:
                # Take the first item if it's a list
                extracted_data = extracted_data[0]
            else:
                # Create empty dict if list is empty
                extracted_data = {}
        
        # Ensure extracted_data is a dictionary
        if not isinstance(extracted_data, dict):
            console.print(f"  [red]Error: LLM returned invalid data type for {filename}. Expected dict, got {type(extracted_data)}[/red]")
            return None
        
        # Add metadata we already know
        extracted_data.update(metadata)
        
        return extracted_data

    except json.JSONDecodeError:
        console.print(f"  [red]Error: Failed to decode JSON from LLM response for {filename}.[/red]")
        console.print(f"  [dim]LLM raw response: {response.text[:200]}...[/dim]")
        return None
    except Exception as e:
        console.print(f"  [red]An error occurred while processing {filename}: {e}[/red]")
        return None

def flatten_json_to_csv(data, parent_key='', sep='_'):
    """Flatten nested JSON structure for CSV output"""
    items = []
    for k, v in data.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_json_to_csv(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            # Handle lists by joining with semicolon
            items.append((new_key, '; '.join(map(str, v))))
        else:
            items.append((new_key, v))
    return dict(items)

def save_to_csv(data, output_file):
    """Save extracted data to CSV format"""
    if not data:
        console.print("No data to save to CSV")
        return
    
    # Flatten the first item to get column headers
    flattened_data = []
    for item in data:
        flattened_item = flatten_json_to_csv(item)
        flattened_data.append(flattened_item)
    
    if not flattened_data:
        console.print("No data to save to CSV")
        return
    
    # Get all unique column names
    all_columns = set()
    for item in flattened_data:
        all_columns.update(item.keys())
    
    # Sort columns for consistent output
    columns = sorted(list(all_columns))
    
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=columns)
        writer.writeheader()
        for item in flattened_data:
            # Fill missing values with empty strings
            row = {col: item.get(col, '') for col in columns}
            writer.writerow(row)
    
    console.print(f"Data saved to CSV: {output_file}")

def main():
    """Main function to orchestrate the CLI tool."""

    parser = argparse.ArgumentParser(
        description="CLI tool to extract structured data from PDF files.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '-o', '--output',
        default="extraction_results.json",
        help="The name of the output JSON file. (default: extraction_results.json)"
    )
    parser.add_argument(
        '-m', '--model',
        default=DEFAULT_MODEL,
        help=f"The name of the Gemini model to use. (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        '-i', '--input-dir',
        default=os.getcwd(),
        help="Path to the directory containing PDF files. (default: current directory)"
    )
    parser.add_argument(
        '--recursive',
        action='store_true',
        help="Search for PDF files recursively in subdirectories. (default: False)"
    )
    parser.add_argument(
        '-s', '--schema',
        default=DEFAULT_EXTRACT_SCHEMA,
        help=f"The name of the extraction schema to use. (default: {DEFAULT_EXTRACT_SCHEMA})"
    )
    parser.add_argument(
        '-t', '--temperature',
        type=float,
        default=DEFAULT_TEMPERATURE,
        help=f"Temperature for the model generation (0.0 to 1.0). (default: {DEFAULT_TEMPERATURE})"
    )
    parser.add_argument(
        '--text-mode',
        action='store_true',
        help="Extract text from files and send to Gemini instead of uploading files directly. Use this for files over 50MB or when file upload fails."
    )
    parser.add_argument(
        '--format',
        choices=['json', 'csv'],
        default='json',
        help="Output format for the results (default: json)"
    )
    
    args = parser.parse_args()

    console.print("[bold magenta]PDF Data Extractor[/bold magenta]")

    if not configure_gemini():
        return

    model = genai.GenerativeModel(
        model_name=args.model,
        system_instruction=ROLE_MESSAGE_PROMPT,
        generation_config=genai.types.GenerationConfig(
            temperature=args.temperature,
            candidate_count=1
        )
    )
    
    input_directory = args.input_dir
    if not os.path.isdir(input_directory):
        console.print(f"[bold red]Error: Input directory not found: {input_directory}[/bold red]")
        return

    extraction_schema = load_extraction_schema(args.schema)
    if not extraction_schema:
        return
    if not extraction_schema.get('fields'):
        console.print(f"[bold red]Error: No fields specified in the extraction schema.[/bold red]")
        return

    pdf_files = []

    if args.recursive:    
        for root, dirs, files in os.walk(input_directory):
            for file in files:
                if file.lower().endswith(".pdf"):
                    pdf_files.append(os.path.join(root, file))
    else:   
        pdf_files = [f for f in os.listdir(input_directory) if f.lower().endswith(".pdf")]

    if not pdf_files:
        console.print(f"[yellow]No PDF files found in: {input_directory}[/yellow]")
        return

    console.print(f"Found [cyan]{len(pdf_files)}[/cyan] PDF file(s) to process in [blue]{input_directory}[/blue] and subdirectories.")

    all_results = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[green]Processing PDFs...", total=len(pdf_files))
        
        for file_path in pdf_files:
            filename = os.path.basename(file_path)
            progress.update(task, description=f"[green]Processing [bold]{filename}[/bold]...")
            
            result = process_file(file_path, model, extraction_schema, args.text_mode)
            if result:
                all_results.append(result)
                console.print(f"  [green]✔ Success:[/green] Extracted data from [bold]{filename}[/bold]")
            else:
                console.print(f"  [red]✖ Failed:[/red] Could not process [bold]{filename}[/bold]")

            progress.advance(task)

    if not all_results:
        console.print("[yellow]Could not extract data from any of the PDF files.[/yellow]")
        return
        
    try:
        if args.format == 'json':
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(all_results, f, indent=4, ensure_ascii=False)
            console.print(f"\n[bold green]✓ Done! All data saved to [cyan]{args.output}[/cyan][/bold green]")
        elif args.format == 'csv':
            save_to_csv(all_results, args.output)
    except Exception as e:
        console.print(f"\n[bold red]Error saving results to file: {e}[/bold red]")

if __name__ == "__main__":
    main()