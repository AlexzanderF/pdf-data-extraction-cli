#!/usr/bin/env python3
import os
import json
import argparse
import pymupdf  # PyMuPDF
import google.generativeai as genai
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
DEFAULT_MODEL = "gemini-2.5-flash-lite-preview-06-17"
DEFAULT_TEMPERATURE = 0.0

with open("subject_tree.md", "r") as f:
    subject_tree = f.read()

ROLE_MESSAGE_PROMPT = """
    You are an expert academic and technical document analysis assistant and expert at data extraction from specialized texts.
    Your task is to extract specific metadata from the provided text, which was extracted from a PDF document.
    The content may be in various languages and use Latin, Cyrillic, or Greek alphabets.
    Accuracy and strict adherence to the specified JSON format are paramount for successful database integration.
"""

LLM_PROMPT = """
    ### INSTRUCTIONS
    1.  **Analyze the Schema**: Carefully examine the Extraction Schema provided below. It defines the structure, data types, and descriptions of the information you need to find.
    2.  **Scan the Document**: Read the document text and identify the data points that match the descriptions in the schema `description` field.
    3.  **Populate the JSON**: Construct a JSON object. The keys in your JSON output **must exactly match** the `keys` from the schema.
    4.  **Handle Missing Data**: If the information is not present, use the JSON value `null`.
    5.  **Respect Data Types**: Extract the data in the correct data type specified in the schema `type` field.
    6.  **Final Output**: Your response **must only contain the final JSON object**. Do not include any explanations, conversational text like "Here is the JSON you requested:" or markdown formatting like ```json ... ``` before or after the JSON object.
    
    ### JSON EXTRACTION SCHEMA:
    {{
      "title_english": {{ "description": "The title of the document, translated into English.", "type": "string" }},
      "title_original": {{ "description": "The title in its original language and script.", "type": "string" }},
      "authors": {{ "description": "List of all author names as strings.", "type": "list_of_strings" }},
      "page_range": {{ "description": "The page range of the main content, like '9-37'. Infer this if possible.", "type": "string" }},
      "doi": {{ "description": "The Digital Object Identifier (DOI).", "type": "string" }},
      "orcid": {{ "description": "The Open Researcher and Contributor ID (ORCID).", "type": "string" }},
      "keywords": {{ "description": "A list of 5-6 relevant keywords in English.", "type": "list_of_strings" }},
      "summary_abstract": {{ "description": "The full summary or abstract text.", "type": "string" }},
      "language": {{ "description": "The language of the document (English, Polish, etc.).", "type": "string" }},
      "article_type": {{ "description": "Select only 1 most suitable article type from this selection: Bibliography, Conference Report, Editorial, Essay, Historical Reference, Interview, Literary Text, Obituary, Other, Review, Scholarly Article, Scientific Life, Source Material, Speech.", "type": "string" }},
      "subjects": {{ "description": "The most suitable subject (1-6) as array of strings from the provided subject tree markdown list. Subjects can be from different branches of the tree list, example: [ \"Social Sciences\", \"Social Sciences / Communication studies / Media studies\", \"Social Sciences / Sociology\" ].", "type": "list_of_strings" }}
    }}

    --- SUBJECT TREE START ---
    {subject_tree}
    --- SUBJECT TREE END ---

    --- DOCUMENT TEXT START ---
    {pdf_text_content}
    --- DOCUMENT TEXT END ---
"""

console = Console()

def configure_gemini():
    """Configures the Gemini API with the key from environment variables."""

    if not GEMINI_API_KEY:
        console.print("[bold red]Error: GOOGLE_API_KEY environment variable not found.[/bold red]")
        console.print("Please set the environment variable before running the script.")
        return False
    
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        return True
    except Exception as e:
        console.print(f"[bold red]An error occurred during Gemini configuration: {e}[/bold red]")
        return False
    
def process_pdf(file_path, model):
    """
    Opens a PDF, extracts relevant text, sends it to Gemini, and parses the result.
    Returns a dictionary with extracted data or None on failure.
    """
    
    filename = os.path.basename(file_path)

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

    prompt = LLM_PROMPT.format(pdf_text_content=pdf_text_content, subject_tree=subject_tree)

    try:
        response = model.generate_content(prompt)
        
        # Clean up potential markdown formatting from the response
        cleaned_response_text = response.text.strip().replace("```json", "").replace("```", "")
        
        extracted_data = json.loads(cleaned_response_text)
        
        # Add data we already know
        extracted_data['filename'] = filename
        extracted_data['page_count'] = page_count
        
        return extracted_data

    except json.JSONDecodeError:
        console.print(f"  [red]Error: Failed to decode JSON from LLM response for {filename}.[/red]")
        console.print(f"  [dim]LLM raw response: {response.text[:200]}...[/dim]")
        return None
    except Exception as e:
        console.print(f"  [red]An error occurred while calling the Gemini API for {filename}: {e}[/red]")
        return None
    
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
    args = parser.parse_args()

    console.print("[bold magenta]PDF Data Extractor[/bold magenta]")

    if not configure_gemini():
        return

    model = genai.GenerativeModel(
        model_name=args.model,
        system_instruction=ROLE_MESSAGE_PROMPT,
        generation_config=genai.types.GenerationConfig(
            temperature=DEFAULT_TEMPERATURE,
            candidate_count=1
        )
    )
    
    input_directory = args.input_dir
    if not os.path.isdir(input_directory):
        console.print(f"[bold red]Error: Input directory not found: {input_directory}[/bold red]")
        return

    pdf_files = [f for f in os.listdir(input_directory) if f.lower().endswith(".pdf")]

    if not pdf_files:
        console.print(f"[yellow]No PDF files found in: {input_directory}[/yellow]")
        return

    console.print(f"Found [cyan]{len(pdf_files)}[/cyan] PDF file(s) to process in [blue]{input_directory}[/blue].")

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
        
        for filename in pdf_files:
            file_path = os.path.join(input_directory, filename)
            progress.update(task, description=f"[green]Processing [bold]{filename}[/bold]...")
            
            result = process_pdf(file_path, model)
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
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, indent=4, ensure_ascii=False)
        console.print(f"\n[bold green]✓ Done! All data saved to [cyan]{args.output}[/cyan][/bold green]")
    except Exception as e:
        console.print(f"\n[bold red]Error saving results to file: {e}[/bold red]")

if __name__ == "__main__":
    main()