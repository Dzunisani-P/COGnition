from fastapi import FastAPI, Request, Form, Depends, Query, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import pandas as pd
import re
import tempfile
import aiohttp
import asyncio
from pathlib import Path
from pydantic import BaseModel

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Set up Jinja2 templates
templates = Jinja2Templates(directory="app/templates")

# Load data
app_dir = Path(__file__).parent
ref = pd.read_csv(app_dir.parent / "data/ref.tsv", sep="\t")
other = pd.read_csv(app_dir.parent / "data/other.tsv", sep="\t")

# Root endpoint to serve the HTML page
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "ref_count": ref.shape[0]})

# Endpoint to filter data
@app.post("/filter")
async def filter_data(
    taxa_list: str = Form(""),
    remove_redundancy: bool = Form(False),
    page: int = Query(1, ge=1),  # Page number, default is 1
    page_size: int = Query(30, ge=1),  # Number of items per page, default is 30
    taxa_file: UploadFile = File(None)  # Optional file upload
):
    """
    Filter the proteomes based on the taxa list input and optionally remove redundancy.
    Supports pagination and file upload.
    """
    taxa_list_combined = []

    # Add manually entered taxa
    if taxa_list:
        taxa_list_combined.extend([taxa.strip().lower() for taxa in taxa_list.split(",")])

    # Add taxa from the uploaded file
    if taxa_file:
        content = await taxa_file.read()
        content = content.decode("utf-8").splitlines()
        taxa_list_combined.extend([line.strip().lower() for line in content if line.strip()])

    # Remove duplicates from the combined taxa list
    taxa_list_combined = list(set(taxa_list_combined))

    # If no taxa list is provided, use the full dataset
    if not taxa_list_combined:
        result = ref
    else:
        filtered_proteomes = pd.DataFrame()

        for taxa in taxa_list_combined:
            escaped_taxa = re.escape(taxa)
            ref_match = ref[ref["Organism"].str.contains(escaped_taxa, case=False, na=False)]
            
            # Apply redundancy logic if the checkbox is selected
            if remove_redundancy and not ref_match.empty:
                ref_match = ref_match.iloc[0:1]

            filtered_proteomes = pd.concat([filtered_proteomes, ref_match]).drop_duplicates()

        result = filtered_proteomes

    # Apply redundancy removal to the entire dataset if no taxa list is provided
    if not taxa_list_combined and remove_redundancy:
        result = result.drop_duplicates(subset=["Organism"], keep="first")

    # Paginate the results
    start = (page - 1) * page_size
    end = start + page_size
    paginated_data = result.iloc[start:end]

    return JSONResponse({
        "count": result.shape[0],  # Total count of proteomes
        "page": page,  # Current page number
        "page_size": page_size,  # Number of items per page
        "preview": paginated_data.to_dict(orient="records")  # Paginated data for the table
    })
    
# Endpoint to download FASTA
@app.post("/download_fasta")
async def download_fasta(
    taxa_list: str = Form(""),
    remove_redundancy: bool = Form(False),
    taxa_file: UploadFile = File(None)
):
    """
    Handle download action by triggering the FASTA download process.
    """
    taxa_list_combined = []

    # Add manually entered taxa
    if taxa_list:
        taxa_list_combined.extend([taxa.strip().lower() for taxa in taxa_list.split(",")])

    # Add taxa from the uploaded file
    if taxa_file:
        content = await taxa_file.read()
        content = content.decode("utf-8").splitlines()
        taxa_list_combined.extend([line.strip().lower() for line in content if line.strip()])

    # Remove duplicates from the combined taxa list
    taxa_list_combined = list(set(taxa_list_combined))

    # If no taxa list is provided, use the full dataset
    if not taxa_list_combined:
        result = ref
    else:
        filtered_proteomes = pd.DataFrame()

        for taxa in taxa_list_combined:
            escaped_taxa = re.escape(taxa)
            ref_match = ref[ref["Organism"].str.contains(escaped_taxa, case=False, na=False)]
            
            # Apply redundancy logic if the checkbox is selected
            if remove_redundancy and not ref_match.empty:
                ref_match = ref_match.iloc[0:1]

            filtered_proteomes = pd.concat([filtered_proteomes, ref_match]).drop_duplicates()

        result = filtered_proteomes

    # Apply redundancy removal to the entire dataset if no taxa list is provided
    if not taxa_list_combined and remove_redundancy:
        result = result.drop_duplicates(subset=["Organism"], keep="first")

    # Fetch FASTA sequences for the filtered proteomes
    proteome_ids = result["Proteome Id"].tolist()
    taxa_list = result["Organism"].tolist()

    if not proteome_ids:
        return JSONResponse({"error": "No proteomes selected"}, status_code=400)

    response = await fetch_proteomes_and_write_fasta(proteome_ids, taxa_list)

    if "errors" in response:
        # Return the FASTA file along with error messages
        return JSONResponse({"fasta_file": response["fasta_file"].as_uri(), "errors": response["errors"]})
    else:
        # Return the FASTA file
        return FileResponse(response["fasta_file"], filename="proteomes.fasta")

async def fetch_fasta_sequence(proteome_id, taxa):
    """
    Fetch FASTA sequence from UniProt for a given proteome ID.
    """
    url = f"https://rest.uniprot.org/uniprotkb/stream?format=fasta&query=proteome:{proteome_id}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.text()
                    return data, proteome_id, taxa  # Return FASTA data, proteome_id, and taxa
                else:
                    error_msg = f"Error downloading proteome for '{taxa}' (Status code: {response.status})"
                    print(error_msg)
                    return None, proteome_id, taxa, error_msg
    except aiohttp.ClientError as e:
        error_msg = f"Network-related error occurred: {e}"
        print(error_msg)
        return None, proteome_id, taxa, error_msg
    except Exception as e:
        error_msg = f"Unexpected error occurred: {e}"
        print(error_msg)
        return None, proteome_id, taxa, error_msg

async def fetch_proteomes_and_write_fasta(proteome_ids, taxa_list):
    """
    Fetch proteomes by their IDs and write the sequences to a FASTA file.
    Uses asyncio.gather to fetch multiple proteomes concurrently.
    """
    fasta_file = Path(tempfile.mktemp(suffix=".fasta"))
    
    tasks = []  # List to hold the asyncio tasks

    # Create tasks for each proteome
    for proteome_id, taxa in zip(proteome_ids, taxa_list):
        tasks.append(fetch_fasta_sequence(proteome_id, taxa))

    # Run all the tasks concurrently using asyncio.gather
    results = await asyncio.gather(*tasks)

    errors = []  # List to collect error messages

    with open(fasta_file, 'w') as f:
        for result in results:
            fasta_sequence, proteome_id, taxa, error_msg = result
            if fasta_sequence:
                f.write(f">{proteome_id} {taxa}\n{fasta_sequence}\n")
            else:
                errors.append(error_msg)
                print(f"Skipping proteome {taxa} due to download error.")

    # If there are errors, return them along with the FASTA file
    if errors:
        return {"fasta_file": fasta_file, "errors": errors}
    else:
        return {"fasta_file": fasta_file}