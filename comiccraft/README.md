# ComicCraft

ComicCraft turns a short idea and a few creative choices into a panel-by-panel comic. It includes a responsive browser studio, a FastAPI JSON API, and a multi-page PDF export.

## Run locally

Use Python 3.10 or newer. From this folder, create and activate a virtual environment, install the dependencies, then start the web server:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Without API keys, the studio still works in demo mode with a sample story and local vector illustrations.

## Enable AI generation

Add provider keys to `.env`, then restart the server:

```dotenv
GEMINI_API_KEY=your_google_ai_studio_key
COMICCRAFT_GEMINI_MODEL=gemini-3.8-flash
HF_TOKEN=your_hugging_face_token
COMICCRAFT_IMAGE_MODEL=stabilityai/stable-diffusion-3.5-large
```

Gemini generates the story as structured JSON. Hugging Face Inference generates an illustration for each panel. You can configure either provider independently; ComicCraft uses local demo content for the provider that is not configured. If image inference fails for an individual panel, that panel receives a local vector illustration so the story remains viewable and exportable.

Provider keys stay on the server and are never sent to browser code. Model identifiers are environment settings so they can be changed without editing the app.

## API

- `GET /api/health` — provider configuration status
- `GET /api/sample` — the illustrated sample comic
- `POST /api/comics` — generate a comic from JSON fields `prompt`, `character_name`, `setting`, `tone`, `art_style`, and `panel_count`
- `GET /api/comics/{comic_id}/pdf` — download a PDF with one illustrated panel per page
- `GET /export/{comic_id}/success` — export confirmation page

## Publish on Render

The included `render.yaml` creates a single public web service named `prithika-comiccraft` in Singapore. Push this project folder to a GitHub, GitLab, or Bitbucket repository, connect that repository to Render, and apply the Blueprint. Add a fresh Gemini key in Render's environment settings as `GEMINI_API_KEY`; add `HF_TOKEN` if you want hosted image generation. Keep provider keys out of the repository.

Comic records are held in the running process memory, while generated artwork is saved under `app/static/generated`. Restarting the server clears comic records, so export a comic before restarting. For a multi-process or hosted deployment, replace the in-memory comic store with persistent storage.
