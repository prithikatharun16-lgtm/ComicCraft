from __future__ import annotations

import html
import io
import json
import logging
import os
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
GENERATED = STATIC / "generated"
TEMPLATES = ROOT / "templates"
GENERATED.mkdir(parents=True, exist_ok=True)

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT.parent / ".env")
except ImportError:
    pass

GEMINI_MODEL = os.getenv("COMICCRAFT_GEMINI_MODEL", "gemini-3.8-flash")
IMAGE_MODEL = os.getenv("COMICCRAFT_IMAGE_MODEL", "stabilityai/stable-diffusion-3.5-large")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("comiccraft")

app = FastAPI(title="ComicCraft", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ComicRequest(BaseModel):
    prompt: str = Field(min_length=8, max_length=1200)
    character_name: str = Field(default="Pip", min_length=1, max_length=50)
    setting: str = Field(default="Enchanted forest", min_length=1, max_length=80)
    tone: Literal["adventurous", "funny", "heartwarming", "mysterious", "dramatic"] = "adventurous"
    art_style: Literal["storybook", "anime", "comic book", "watercolor", "pixel art"] = "storybook"
    panel_count: int = Field(default=4, ge=3, le=6)


class Panel(BaseModel):
    number: int
    title: str
    narration: str
    dialogue: str
    image_prompt: str
    image_url: str
    image_kind: Literal["generated", "demo"]


class Comic(BaseModel):
    id: str
    title: str
    tagline: str
    created_at: str
    generation: dict[str, str]
    panels: list[Panel]
    preferences: dict[str, str | int]


COMICS: dict[str, Comic] = {}


def _safe_text(value: str, limit: int = 220) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _json_from_model(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def _gemini_story(data: ComicRequest) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_KEY)
    instruction = f"""Create an original, cohesive comic in {data.panel_count} panels.
User idea: {data.prompt}
Main character name: {data.character_name}
Setting: {data.setting}
Tone: {data.tone}
Visual art direction: {data.art_style}

Return only JSON with this exact shape:
{{"title":"short comic title","tagline":"one short line","panels":[{{"title":"brief beat title","narration":"one or two vivid sentences, max 35 words","dialogue":"one short spoken line, max 16 words","image_prompt":"a concise visual description of this exact moment, with consistent character appearance and the requested art direction"}}]}}
Include exactly {data.panel_count} panels. Give the story a clear beginning, turn, and satisfying ending. Keep the same character appearance across every image prompt. Avoid lettering, captions, speech bubbles, logos, and watermarks in image prompts."""
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=instruction,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    result = _json_from_model(response.text or "")
    panels = result.get("panels")
    if not isinstance(panels, list) or len(panels) != data.panel_count:
        raise ValueError("The story model returned an unexpected number of panels.")
    return result


def _demo_story(data: ComicRequest) -> dict:
    name = _safe_text(data.character_name, 50) or "Pip"
    prompt = _safe_text(data.prompt, 180)
    setting = _safe_text(data.setting, 80)
    if data.tone == "funny":
        beats = [
            ("A very serious quest", f"{name} marched into {setting} with a map, a snack, and absolutely no plan.", "I meant to pack the map upside down."),
            ("The suspicious clue", f"A trail of glittering crumbs led {name} to a door no taller than a teacup.", "Either this is a clue or a tiny picnic."),
            ("Unexpected company", f"Behind it, a proud little dragon was trying to sneeze out a sunflower.", "Could you say 'bless you' before the next one?"),
            ("The grand solution", f"Together they found the missing seed—and planted it right beside the door.", "Quest complete. Snack break forever."),
            ("A towering surprise", f"By morning, one sunflower had grown taller than all of {setting}.", "I knew we should've brought a bigger map."),
            ("The new tradition", f"{name} and the dragon met there every week for sunflower tea.", "Next time, I'm packing two maps."),
        ]
    elif data.tone == "mysterious":
        beats = [
            ("The strange signal", f"At dusk, {name} noticed a blue light blinking deep inside {setting}.", "That light wasn't there yesterday."),
            ("Footsteps behind", f"Every step closer brought a second set of footsteps just out of sight.", "If you're friendly, you can come say hello."),
            ("The hidden door", f"A quiet voice answered from beneath a circle of ancient stones.", "The key is already in your hand."),
            ("The answer below", f"{name} opened a secret room and found a tiny star waiting to go home.", "The sky has been looking for you."),
            ("A sky remembered", f"Together they returned the star to the night above {setting}.", "Look—the constellations are changing."),
            ("One last glimmer", f"On the path back, a new blue light winked from {name}'s pocket.", "I suppose the mystery isn't over."),
        ]
    else:
        beats = [
            ("The first step", f"{name} set off through {setting}, carrying one hopeful idea: {prompt}.", "There has to be a way."),
            ("A little help", f"A new friend appeared just when the path seemed impossible.", "We can figure it out together."),
            ("The hard part", f"A sudden storm tested their courage, but neither of them turned back.", "One more step. Then another."),
            ("A bright discovery", f"At the heart of {setting}, {name} found a way to make the idea real.", "We did it—and we did it together."),
            ("The ripple", f"Their small act brought light and laughter to everyone nearby.", "Look how far one brave idea can travel."),
            ("A new beginning", f"As the sun set, {name} was already dreaming up the next adventure.", "Tomorrow, let's see what's over that hill."),
        ]
    selected = beats[: data.panel_count]
    return {
        "title": f"{name} and the {setting.split()[0]} Secret",
        "tagline": f"A {data.tone} little adventure, made just for you.",
        "panels": [
            {
                "title": title,
                "narration": narration,
                "dialogue": dialogue,
                "image_prompt": f"{data.art_style} comic illustration, {setting}, {name} in a memorable story moment: {narration}",
            }
            for title, narration, dialogue in selected
        ],
    }


def _scene_svg(index: int, description: str, setting: str, style: str) -> str:
    """A lightweight, original vector scene used when image inference is not configured."""
    safe_setting = html.escape(setting[:55])
    palette = [("#f6c76e", "#d77752", "#416b57"), ("#f5a97b", "#db5d4c", "#294c59"), ("#d9bcf0", "#8f6aa8", "#405e58"), ("#f3d98b", "#dc8857", "#536c4a"), ("#adcce4", "#697fbd", "#3f6473"), ("#eeb0a5", "#c85d64", "#51466d")]
    sky, glow, ground = palette[(index - 1) % len(palette)]
    sun_x = 704 - (index % 3) * 78
    star_points = " ".join(f"{x},{y}" for x, y in [(95, 85), (242, 142), (438, 70), (612, 168), (781, 99)])
    trees = "".join(
        f'<path d="M{x} 392 L{x+38} {245+(x%36)} L{x+76} 392Z" fill="{ground}" opacity="{opacity}"/><rect x="{x+32}" y="376" width="12" height="85" fill="#4e4b42"/>'
        for x, opacity in [(28, ".84"), (156, ".7"), (684, ".78"), (790, ".9")]
    )
    captions = html.escape((description.split(":")[-1].strip() or "A new adventure begins")[:100])
    style_label = html.escape(style.title())
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="880" height="560" viewBox="0 0 880 560">
<rect width="880" height="560" fill="{sky}"/><circle cx="{sun_x}" cy="132" r="54" fill="{glow}" opacity=".78"/>
<path d="M0 347 Q174 286 337 360T670 339T880 331V560H0Z" fill="{ground}" opacity=".55"/>
{trees}<path d="M0 450 Q155 397 301 450T589 433T880 421V560H0Z" fill="{ground}"/>
<path d="M370 560 Q389 486 473 459 Q519 442 532 412" fill="none" stroke="#f4d5a5" stroke-width="30" opacity=".85"/>
<g fill="#fff5d8" opacity=".85"><circle cx="106" cy="110" r="4"/><circle cx="290" cy="74" r="3"/><circle cx="529" cy="128" r="4"/><circle cx="760" cy="218" r="3"/><circle cx="191" cy="194" r="3"/></g>
<g transform="translate({275 + (index%3)*48} {312 - (index%2)*18})">
<ellipse cx="48" cy="121" rx="48" ry="15" fill="#27362f" opacity=".2"/><path d="M23 93 Q9 123 3 142 Q36 129 50 105Z" fill="#c96443" stroke="#493f3a" stroke-width="5"/>
<ellipse cx="49" cy="94" rx="32" ry="39" fill="#dc7950" stroke="#493f3a" stroke-width="5"/><path d="M27 66 L23 23 L49 51 L68 22 L74 68Z" fill="#dc7950" stroke="#493f3a" stroke-width="5"/>
<ellipse cx="50" cy="100" rx="20" ry="23" fill="#f4d8b1"/><circle cx="42" cy="84" r="3.5" fill="#282d2c"/><circle cx="61" cy="84" r="3.5" fill="#282d2c"/><path d="M47 96 Q52 101 57 96" fill="none" stroke="#593f37" stroke-width="3" stroke-linecap="round"/>
<path d="M30 125 L25 146 M66 125 L72 146" stroke="#493f3a" stroke-width="8" stroke-linecap="round"/>
</g>
<rect x="24" y="24" width="146" height="34" rx="17" fill="#fffaf0" opacity=".82"/><text x="43" y="47" fill="#493f3a" font-family="Arial,sans-serif" font-size="15" font-weight="700">{style_label} • PANEL {index:02d}</text>
<text x="36" y="519" fill="#fffaf0" stroke="#394b42" stroke-width="1.4" paint-order="stroke" font-family="Georgia,serif" font-size="20" font-weight="700">{safe_setting}</text>
<title>{captions}</title></svg>'''


def _save_art(panel: dict, comic_id: str, index: int, data: ComicRequest) -> tuple[str, str]:
    filename_base = f"{comic_id}-{index:02d}"
    if HF_TOKEN:
        try:
            from huggingface_hub import InferenceClient

            client = InferenceClient(model=IMAGE_MODEL, token=HF_TOKEN, timeout=120)
            visual_prompt = (
                f"{panel['image_prompt']}. {data.art_style} comic panel illustration, "
                "cinematic composition, clear readable shapes, rich color, same character design, "
                "no text, no letters, no speech bubbles, no watermark"
            )
            image = client.text_to_image(visual_prompt, width=768, height=512)
            output = io.BytesIO()
            image.save(output, format="PNG")
            (GENERATED / f"{filename_base}.png").write_bytes(output.getvalue())
            return f"/static/generated/{filename_base}.png", "generated"
        except Exception:
            logger.exception("Image generation failed; using the local demo illustration.")
    svg = _scene_svg(index, panel.get("image_prompt", ""), data.setting, data.art_style)
    (GENERATED / f"{filename_base}.svg").write_text(svg, encoding="utf-8")
    return f"/static/generated/{filename_base}.svg", "demo"


def _compose_comic(data: ComicRequest, comic_id: str) -> Comic:
    generated_story = bool(GEMINI_KEY)
    try:
        story = _gemini_story(data) if generated_story else _demo_story(data)
    except Exception as exc:
        logger.exception("Story generation failed")
        raise HTTPException(status_code=502, detail="The story model could not create this comic. Check the Gemini API key and model setting, then try again.") from exc

    output_panels: list[Panel] = []
    for index, item in enumerate(story["panels"], start=1):
        panel_data = {
            "title": _safe_text(str(item.get("title", f"Panel {index}")), 90),
            "narration": _safe_text(str(item.get("narration", "")), 320),
            "dialogue": _safe_text(str(item.get("dialogue", "")), 180),
            "image_prompt": _safe_text(str(item.get("image_prompt", "")), 500),
        }
        image_url, image_kind = _save_art(panel_data, comic_id, index, data)
        output_panels.append(Panel(number=index, **panel_data, image_url=image_url, image_kind=image_kind))

    generated_images = sum(panel.image_kind == "generated" for panel in output_panels)
    image_mode = "Hugging Face illustrations" if generated_images == len(output_panels) else (
        "local vector demo art" if generated_images == 0 else "Hugging Face + demo illustrations"
    )
    story_mode = f"Gemini {GEMINI_MODEL}" if generated_story else "local demo story"
    return Comic(
        id=comic_id,
        title=_safe_text(str(story.get("title", "A ComicCraft Adventure")), 100),
        tagline=_safe_text(str(story.get("tagline", "A little story made just for you.")), 180),
        created_at=datetime.now(timezone.utc).isoformat(),
        generation={"story": story_mode, "art": image_mode},
        panels=output_panels,
        preferences={
            "character_name": data.character_name,
            "setting": data.setting,
            "tone": data.tone,
            "art_style": data.art_style,
            "panel_count": data.panel_count,
        },
    )


def _sample_comic() -> Comic:
    sample_id = "sample-fox"
    data = ComicRequest(
        prompt="A brave fox explores an enchanted forest and discovers a tiny star that has fallen from the sky.",
        character_name="Pip",
        setting="Enchanted forest",
        tone="adventurous",
        art_style="storybook",
        panel_count=4,
    )
    if sample_id not in COMICS:
        story = _demo_story(data)
        panels: list[Panel] = []
        for index, item in enumerate(story["panels"], start=1):
            image_url = f"/static/generated/{sample_id}-{index:02d}.svg"
            (GENERATED / f"{sample_id}-{index:02d}.svg").write_text(
                _scene_svg(index, item["image_prompt"], data.setting, data.art_style), encoding="utf-8"
            )
            panels.append(Panel(number=index, **item, image_url=image_url, image_kind="demo"))
        COMICS[sample_id] = Comic(
            id=sample_id,
            title="Pip & the fallen star",
            tagline="A tiny light. A very big adventure.",
            created_at=datetime.now(timezone.utc).isoformat(),
            generation={"story": "sample story", "art": "sample illustrations"},
            panels=panels,
            preferences={"character_name": "Pip", "setting": "Enchanted forest", "tone": "adventurous", "art_style": "storybook", "panel_count": 4},
        )
    return COMICS[sample_id]


@app.get("/", response_class=HTMLResponse)
async def home() -> FileResponse:
    return FileResponse(TEMPLATES / "index.html")


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "story_model": GEMINI_MODEL if GEMINI_KEY else "demo",
        "image_model": IMAGE_MODEL if HF_TOKEN else "demo",
        "gemini_configured": bool(GEMINI_KEY),
        "images_configured": bool(HF_TOKEN),
    }


@app.get("/api/sample", response_model=Comic)
async def sample() -> Comic:
    return _sample_comic()


@app.post("/api/comics", response_model=Comic)
async def create_comic(request: ComicRequest) -> Comic:
    comic_id = uuid.uuid4().hex[:12]
    comic = await run_in_threadpool(_compose_comic, request, comic_id)
    COMICS[comic_id] = comic
    return comic


def _ascii(text: str) -> str:
    normalized = text.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-", "…": "..."}))
    return unicodedata.normalize("NFKD", normalized).encode("ascii", errors="replace").decode("ascii")


@app.get("/api/comics/{comic_id}/pdf")
async def export_pdf(comic_id: str) -> Response:
    comic = COMICS.get(comic_id)
    if comic is None:
        raise HTTPException(status_code=404, detail="This comic is no longer available. Generate it again to export a fresh copy.")
    try:
        from fpdf import FPDF

        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=16)
        for panel in comic.panels:
            pdf.add_page()
            pdf.set_fill_color(252, 247, 237)
            pdf.rect(0, 0, 210, 297, style="F")
            pdf.set_text_color(42, 44, 40)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(196, 91, 57)
            pdf.cell(0, 8, _ascii(f"COMICCRAFT     {panel.number:02d} / {len(comic.panels):02d}"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(42, 44, 40)
            pdf.set_font("Helvetica", "B", 24)
            pdf.multi_cell(0, 12, _ascii(comic.title), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "B", 15)
            pdf.multi_cell(0, 9, _ascii(panel.title), new_x="LMARGIN", new_y="NEXT")
            image_path = (STATIC / panel.image_url.removeprefix("/static/")).resolve()
            if not image_path.is_relative_to(GENERATED.resolve()) or not image_path.exists():
                raise HTTPException(status_code=500, detail="A comic illustration is missing. Please generate the comic again.")
            pdf.image(str(image_path), x=15, y=75, w=180, h=114)
            pdf.set_y(200)
            pdf.set_font("Helvetica", size=13)
            pdf.set_text_color(61, 61, 55)
            pdf.multi_cell(0, 8, _ascii(panel.narration), new_x="LMARGIN", new_y="NEXT")
            if panel.dialogue:
                pdf.ln(5)
                pdf.set_font("Helvetica", "I", 12)
                pdf.set_text_color(188, 83, 52)
                pdf.multi_cell(0, 8, _ascii(f'“{panel.dialogue}”'), new_x="LMARGIN", new_y="NEXT")
            pdf.set_y(-18)
            pdf.set_font("Helvetica", size=8)
            pdf.set_text_color(135, 126, 111)
            pdf.cell(0, 6, _ascii(comic.tagline), align="C")
        payload = bytes(pdf.output())
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("PDF export failed")
        raise HTTPException(status_code=500, detail="PDF export failed. Please try again.") from exc

    filename = f"comiccraft-{comic.id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/export/{comic_id}/success", response_class=HTMLResponse)
async def export_success(comic_id: str) -> FileResponse:
    if comic_id not in COMICS:
        raise HTTPException(status_code=404, detail="This comic is no longer available.")
    page = (TEMPLATES / "success.html").read_text(encoding="utf-8")
    page = page.replace("{{COMIC_ID}}", html.escape(comic_id)).replace("{{COMIC_TITLE}}", html.escape(COMICS[comic_id].title))
    return HTMLResponse(page)
