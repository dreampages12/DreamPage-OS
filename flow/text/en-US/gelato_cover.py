import json
import os
import urllib.parse
import urllib.request

from PIL import Image, ImageFilter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


COVER_DPI = 300

PRODUCT_UID_BY_COVER_TYPE = {
    "hardcover": "photobooks-hardcover_pf_200x200-mm-8x8-inch_pt_170-gsm-65lb-coated-silk_cl_4-4_ccl_4-4_bt_glued-left_ct_matt-lamination_prt_1-0_cpt_130-gsm-65-lb-cover-coated-silk_ver",
    "softcover": "photobooks-softcover_pf_200x200-mm-8x8-inch_pt_170-gsm-65lb-coated-silk_cl_4-4_ccl_4-4_bt_glued-left_ct_matt-lamination_prt_1-0_cpt_250-gsm-100-lb-cover-coated-silk_ver",
}


def mm_to_px(mm_value: float, dpi: int = COVER_DPI) -> int:
    return max(1, int(round((float(mm_value) / 25.4) * dpi)))


def mm_to_points(mm_value: float) -> float:
    return (float(mm_value) / 25.4) * inch


def px_to_mm(px_value: float, dpi: int = COVER_DPI) -> float:
    return (float(px_value) / float(dpi)) * 25.4


def fetch_cover_layout(api_key: str, cover_type: str, page_count: int) -> dict:
    if not api_key:
        raise ValueError("Missing Gelato API key for cover layout lookup")

    normalized_cover_type = (cover_type or "softcover").strip().lower()
    product_uid = PRODUCT_UID_BY_COVER_TYPE.get(normalized_cover_type)
    if not product_uid:
        raise ValueError(f"Unsupported cover type: {cover_type}")

    query = urllib.parse.urlencode({"pageCount": int(page_count)})
    url = f"https://product.gelatoapis.com/v3/products/{product_uid}/cover-dimensions?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "X-API-KEY": api_key,
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)

    total_size = payload.get("wraparoundInsideSize") or payload.get("bleedSize")
    back_content = payload.get("contentBackSize")
    front_content = payload.get("contentFrontSize")
    spine = payload.get("spineSize")

    if not total_size or not back_content or not front_content or not spine:
        raise ValueError(f"Unexpected Gelato cover layout response: {payload}")

    return {
        "product_uid": payload.get("productUid", product_uid),
        "pages_count": payload.get("pagesCount", int(page_count)),
        "total_size": total_size,
        "back_content": back_content,
        "front_content": front_content,
        "spine": spine,
    }


def _anchored_offset(container: int, content: int, anchor: str) -> int:
    if anchor in ("left", "top"):
        return 0
    if anchor in ("right", "bottom"):
        return container - content
    return int(round((container - content) / 2))


def _anchored_crop_start(size: int, target: int, anchor: str) -> int:
    if size <= target:
        return 0
    if anchor in ("left", "top"):
        return 0
    if anchor in ("right", "bottom"):
        return size - target
    return int(round((size - target) / 2))


def _extend_edges(canvas_img: Image.Image, placed_box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = placed_box
    width, height = canvas_img.size

    if x0 > 0:
        left_strip = canvas_img.crop((x0, y0, x0 + 1, y1)).resize((x0, y1 - y0), Image.LANCZOS)
        canvas_img.paste(left_strip, (0, y0))
    if x1 < width:
        right_strip = canvas_img.crop((x1 - 1, y0, x1, y1)).resize((width - x1, y1 - y0), Image.LANCZOS)
        canvas_img.paste(right_strip, (x1, y0))
    if y0 > 0:
        top_strip = canvas_img.crop((0, y0, width, y0 + 1)).resize((width, y0), Image.LANCZOS)
        canvas_img.paste(top_strip, (0, 0))
    if y1 < height:
        bottom_strip = canvas_img.crop((0, y1 - 1, width, y1)).resize((width, height - y1), Image.LANCZOS)
        canvas_img.paste(bottom_strip, (0, y1))


def _build_blurred_background(
    source_image: Image.Image,
    region_width_px: int,
    region_height_px: int,
) -> Image.Image:
    blurred = source_image.resize((region_width_px, region_height_px), Image.LANCZOS)
    return blurred.filter(ImageFilter.GaussianBlur(24))


def _paste_into_box(
    base_canvas: Image.Image,
    source_image: Image.Image,
    *,
    box_left_px: int,
    box_top_px: int,
    box_width_px: int,
    box_height_px: int,
    anchor_x: str = "center",
    anchor_y: str = "center",
    overscale: float = 1.0,
    fit_axis: str = "contain",
    extend_inside_box: bool = True,
) -> None:
    iw, ih = source_image.size
    if fit_axis == "height":
        scale = (box_height_px / ih) * float(overscale)
    elif fit_axis == "width":
        scale = (box_width_px / iw) * float(overscale)
    elif fit_axis == "cover":
        scale = max(box_width_px / iw, box_height_px / ih) * float(overscale)
    else:
        scale = min(box_width_px / iw, box_height_px / ih) * float(overscale)

    new_width = max(1, int(round(iw * scale)))
    new_height = max(1, int(round(ih * scale)))
    foreground = source_image.resize((new_width, new_height), Image.LANCZOS)

    crop_left = _anchored_crop_start(new_width, box_width_px, anchor_x)
    crop_top = _anchored_crop_start(new_height, box_height_px, anchor_y)
    crop_right = min(new_width, crop_left + box_width_px)
    crop_bottom = min(new_height, crop_top + box_height_px)
    if crop_left or crop_top or crop_right != new_width or crop_bottom != new_height:
        foreground = foreground.crop((crop_left, crop_top, crop_right, crop_bottom))
        new_width, new_height = foreground.size

    x = box_left_px + _anchored_offset(box_width_px, new_width, anchor_x)
    y = box_top_px + _anchored_offset(box_height_px, new_height, anchor_y)

    base_canvas.paste(foreground, (x, y))
    if extend_inside_box:
        box_canvas = base_canvas.crop((box_left_px, box_top_px, box_left_px + box_width_px, box_top_px + box_height_px))
        _extend_edges(
            box_canvas,
            (
                x - box_left_px,
                y - box_top_px,
                x - box_left_px + new_width,
                y - box_top_px + new_height,
            ),
        )
        base_canvas.paste(box_canvas, (box_left_px, box_top_px))


def _compose_region(
    source_image: Image.Image,
    region_box: dict,
    content_box: dict,
    total_height_mm: float,
    anchor_x: str = "center",
    anchor_y: str = "center",
    overscale: float = 1.0,
    fit_axis: str = "contain",
    blur_background: bool = True,
    sharp_box_left_mm: float | None = None,
    sharp_box_width_mm: float | None = None,
) -> Image.Image:
    region_width_px = mm_to_px(region_box["width"])
    region_height_px = mm_to_px(total_height_mm)

    region_canvas = (
        _build_blurred_background(source_image, region_width_px, region_height_px)
        if blur_background
        else Image.new("RGB", (region_width_px, region_height_px), (255, 255, 255))
    )

    box_left_px = mm_to_px(sharp_box_left_mm if sharp_box_left_mm is not None else (content_box["left"] - region_box["left"]))
    box_top_px = mm_to_px(content_box["top"])
    box_width_px = mm_to_px(sharp_box_width_mm if sharp_box_width_mm is not None else content_box["width"])
    box_height_px = mm_to_px(content_box["height"])

    _paste_into_box(
        region_canvas,
        source_image,
        box_left_px=box_left_px,
        box_top_px=box_top_px,
        box_width_px=box_width_px,
        box_height_px=box_height_px,
        anchor_x=anchor_x,
        anchor_y=anchor_y,
        overscale=overscale,
        fit_axis=fit_axis,
        extend_inside_box=True,
    )
    return region_canvas


def build_gelato_cover_pdf(
    *,
    back_image_path: str,
    spine_image_path: str,
    front_image_path: str,
    out_pdf_path: str,
    cover_type: str,
    page_count: int,
    api_key: str,
) -> dict:
    layout = fetch_cover_layout(api_key=api_key, cover_type=cover_type, page_count=page_count)
    total_size = layout["total_size"]
    back_content = layout["back_content"]
    front_content = layout["front_content"]
    spine = layout["spine"]

    total_width_mm = float(total_size["width"])
    total_height_mm = float(total_size["height"])
    spine_left_mm = float(spine["left"])
    spine_width_mm = float(spine["width"])
    front_region_left_mm = spine_left_mm + spine_width_mm
    back_joint_width_mm = spine_left_mm - (float(back_content["left"]) + float(back_content["width"]))
    front_joint_width_mm = float(front_content["left"]) - front_region_left_mm

    back_region = {
        "left": 0.0,
        "width": spine_left_mm,
    }
    spine_region = {
        "left": spine_left_mm,
        "width": spine_width_mm,
    }
    front_region = {
        "left": front_region_left_mm,
        "width": total_width_mm - front_region_left_mm,
    }

    back_image = Image.open(back_image_path).convert("RGB")
    spine_image = Image.open(spine_image_path).convert("RGB")
    front_image = Image.open(front_image_path).convert("RGB")

    total_height_px = mm_to_px(total_height_mm)
    desired_spine_width_mm = px_to_mm(spine_image.width * (total_height_px / float(spine_image.height)))
    max_spine_width_mm = spine_width_mm + back_joint_width_mm + front_joint_width_mm
    visible_spine_width_mm = max(spine_width_mm, min(desired_spine_width_mm, max_spine_width_mm))
    spine_overlap_each_side_mm = max(0.0, (visible_spine_width_mm - spine_width_mm) / 2.0)
    spine_overlay_region = {
        "left": spine_left_mm - spine_overlap_each_side_mm,
        "width": visible_spine_width_mm,
    }

    back_panel = _compose_region(
        back_image,
        back_region,
        back_content,
        total_height_mm,
        anchor_x="right",
        anchor_y="top",
        overscale=1.0,
        fit_axis="contain",
        blur_background=True,
        sharp_box_left_mm=float(back_content["left"]) - float(back_region["left"]),
        sharp_box_width_mm=float(back_region["width"]) - (float(back_content["left"]) - float(back_region["left"])),
    )
    spine_panel = _compose_region(
        spine_image,
        spine_overlay_region,
        spine,
        total_height_mm,
        anchor_x="center",
        anchor_y="center",
        overscale=1.0,
        fit_axis="height",
        blur_background=True,
        sharp_box_left_mm=0.0,
        sharp_box_width_mm=float(spine_overlay_region["width"]),
    )
    front_panel = _compose_region(
        front_image,
        front_region,
        front_content,
        total_height_mm,
        anchor_x="left",
        anchor_y="top",
        overscale=1.0,
        fit_axis="contain",
        blur_background=True,
        sharp_box_left_mm=0.0,
        sharp_box_width_mm=(float(front_content["left"]) - float(front_region["left"])) + float(front_content["width"]),
    )

    total_width_px = mm_to_px(total_width_mm)
    cover_image = Image.new("RGB", (total_width_px, total_height_px), (255, 255, 255))
    cover_image.paste(back_panel, (0, 0))
    cover_image.paste(front_panel, (mm_to_px(front_region["left"]), 0))
    cover_image.paste(spine_panel, (mm_to_px(spine_overlay_region["left"]), 0))

    out_dir = os.path.dirname(os.path.abspath(out_pdf_path))
    cover_tmp_path = os.path.join(out_dir, "_cover_composite.jpg")
    cover_image.save(cover_tmp_path, "JPEG", quality=95)

    pdf_width = mm_to_points(total_width_mm)
    pdf_height = mm_to_points(total_height_mm)
    pdf = canvas.Canvas(out_pdf_path, pagesize=(pdf_width, pdf_height))
    pdf.drawImage(cover_tmp_path, 0, 0, width=pdf_width, height=pdf_height)
    pdf.showPage()
    pdf.save()

    return {
        "cover_pdf_path": out_pdf_path,
        "cover_tmp_path": cover_tmp_path,
        "width_mm": total_width_mm,
        "height_mm": total_height_mm,
        "pages_count": layout["pages_count"],
        "product_uid": layout["product_uid"],
    }
