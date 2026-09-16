import numpy as np
import torch

try:
    from scipy import ndimage
except Exception:
    ndimage = None


def _as_batch(mask):
    if mask.dim() == 2:
        return mask.unsqueeze(0)
    return mask


def _resize_mask(mask, height, width):
    if mask.shape[-2:] == (height, width):
        return mask
    return torch.nn.functional.interpolate(
        mask.unsqueeze(1),
        size=(height, width),
        mode="bilinear",
        align_corners=False,
    ).squeeze(1)


def _largest_component(binary):
    if ndimage is None:
        ys, xs = np.where(binary)
        if len(xs) == 0:
            return binary
        out = np.zeros_like(binary, dtype=bool)
        out[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1] = binary[
            ys.min() : ys.max() + 1, xs.min() : xs.max() + 1
        ]
        return out

    labels, count = ndimage.label(binary)
    if count == 0:
        return binary

    areas = np.bincount(labels.reshape(-1))
    areas[0] = 0
    return labels == areas.argmax()


def _smooth_binary(binary, close_px, open_px, feather_px):
    if ndimage is None:
        return binary.astype(np.float32)

    out = binary
    if close_px > 0:
        out = ndimage.binary_closing(out, structure=np.ones((close_px, close_px)))
        out = ndimage.binary_fill_holes(out)
    if open_px > 0:
        out = ndimage.binary_opening(out, structure=np.ones((open_px, open_px)))

    out = out.astype(np.float32)
    if feather_px > 0:
        sigma = max(0.1, feather_px / 2.0)
        out = ndimage.gaussian_filter(out, sigma=sigma)
        out = np.clip(out, 0.0, 1.0)
    return out


def _trim_shoulder_base(binary):
    rows = np.where(binary.any(axis=1))[0]
    if len(rows) < 8:
        return binary

    widths = np.zeros(binary.shape[0], dtype=np.float32)
    for y in rows:
        xs = np.where(binary[y])[0]
        widths[y] = float(xs.max() - xs.min() + 1) if len(xs) else 0.0

    top = int(rows.min())
    bottom = int(rows.max())
    max_width = max(1.0, float(widths.max()))
    min_width = max(1.0, 0.28 * max_width)

    # Ignore tiny end artifacts, then look for a neck valley followed by a width increase.
    valid = [y for y in range(top, bottom + 1) if widths[y] >= min_width]
    if len(valid) < 8:
        return binary

    search_start = valid[int(len(valid) * 0.48)]
    search_end = valid[-1]
    best_y = None
    best_score = 0.0
    for y in range(search_start + 2, search_end - 2):
        prev_w = np.mean(widths[max(top, y - 5) : y + 1])
        next_w = np.mean(widths[y + 1 : min(bottom + 1, y + 8)])
        if prev_w <= 0:
            continue
        growth = next_w / prev_w
        narrowness = 1.0 - min(1.0, prev_w / max_width)
        score = (growth - 1.0) * narrowness
        if growth > 1.08 and score > best_score:
            best_score = score
            best_y = y

    if best_y is None:
        return binary

    trimmed = binary.copy()
    trimmed[best_y + 1 :, :] = False
    return trimmed


class HumanHeadHairMaskGuard:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "face_anchor_mask": ("MASK",),
                "candidate_mask": ("MASK",),
                "anchor_threshold": (
                    "FLOAT",
                    {"default": 0.35, "min": 0.01, "max": 1.0, "step": 0.01},
                ),
                "candidate_threshold": (
                    "FLOAT",
                    {"default": 0.25, "min": 0.01, "max": 1.0, "step": 0.01},
                ),
                "top_expand_face_heights": (
                    "FLOAT",
                    {"default": 0.85, "min": 0.0, "max": 4.0, "step": 0.05},
                ),
                "side_expand_face_widths": (
                    "FLOAT",
                    {"default": 1.65, "min": 0.5, "max": 5.0, "step": 0.05},
                ),
                "bottom_expand_face_heights": (
                    "FLOAT",
                    {"default": 0.35, "min": 0.0, "max": 4.0, "step": 0.05},
                ),
                "lower_taper_width": (
                    "FLOAT",
                    {"default": 0.25, "min": 0.1, "max": 2.0, "step": 0.05},
                ),
                "anchor_dilate_face_widths": (
                    "FLOAT",
                    {"default": 0.28, "min": 0.0, "max": 2.0, "step": 0.05},
                ),
                "close_pixels": (
                    "INT",
                    {"default": 9, "min": 0, "max": 128, "step": 1},
                ),
                "remove_noise_pixels": (
                    "INT",
                    {"default": 5, "min": 0, "max": 64, "step": 1},
                ),
                "feather_pixels": (
                    "INT",
                    {"default": 1, "min": 0, "max": 64, "step": 1},
                ),
            }
        }

    RETURN_TYPES = ("MASK", "MASK")
    RETURN_NAMES = ("MASK", "HEAD_ROI")
    FUNCTION = "execute"
    CATEGORY = "mask/head hair"

    def _guard_one(
        self,
        face_anchor,
        candidate,
        anchor_threshold,
        candidate_threshold,
        top_expand,
        side_expand,
        bottom_expand,
        lower_taper_width,
        anchor_dilate_widths,
        close_pixels,
        remove_noise_pixels,
        feather_pixels,
    ):
        h, w = candidate.shape
        anchor = face_anchor > anchor_threshold
        candidate = candidate > candidate_threshold

        anchor = _largest_component(anchor)
        ys, xs = np.where(anchor)
        if len(xs) == 0:
            return np.zeros((h, w), dtype=np.float32), np.zeros((h, w), dtype=np.float32)

        x1, x2 = int(xs.min()), int(xs.max()) + 1
        y1, y2 = int(ys.min()), int(ys.max()) + 1
        face_w = max(4, x2 - x1)
        face_h = max(4, y2 - y1)
        cx = (x1 + x2) / 2.0

        # Some detectors/SAM hints return a bust-shaped anchor instead of a true face/head
        # anchor. A bust anchor makes every downstream geometric cutoff too low, which is
        # exactly how shoulders/body leak into the final mask. Normalize suspiciously tall
        # anchors to a plausible head height based on the anchor width.
        max_head_h = int(round(face_w * 1.22))
        if face_h > max_head_h:
            y2 = min(y2, y1 + max_head_h)
            face_h = max(4, y2 - y1)

        top = max(0, int(round(y1 - top_expand * face_h)))
        bottom = min(h, int(round(y2 + bottom_expand * face_h)))

        roi = np.zeros((h, w), dtype=bool)
        lower_start = y2
        lower_span = max(1, bottom - lower_start)
        chin_bridge_end = min(bottom, int(round(y2 + 0.18 * face_h)))

        for y in range(top, bottom):
            if y <= lower_start:
                half_width = side_expand * face_w
                lx = max(0, int(round(cx - half_width)))
                rx = min(w, int(round(cx + half_width)))
                roi[y, lx:rx] = True
            elif y <= chin_bridge_end:
                # Keep a small continuous chin/jaw bridge, but never the shoulders.
                t = min(1.0, max(0.0, (y - lower_start) / max(1, chin_bridge_end - lower_start)))
                width_scale = side_expand + (0.75 - side_expand) * t
                half_width = width_scale * face_w
                lx = max(0, int(round(cx - half_width)))
                rx = min(w, int(round(cx + half_width)))
                roi[y, lx:rx] = True
            else:
                # Below the chin, block the center chest area. Only side hair is allowed.
                t = min(1.0, max(0.0, (y - lower_start) / lower_span))
                outer_scale = side_expand + (0.9 - side_expand) * t
                inner_scale = 0.45 + (lower_taper_width - 0.45) * t
                outer_half = max(inner_scale * face_w, outer_scale * face_w)
                inner_half = max(0.1 * face_w, inner_scale * face_w)
                left_outer = max(0, int(round(cx - outer_half)))
                left_inner = max(0, int(round(cx - inner_half)))
                right_inner = min(w, int(round(cx + inner_half)))
                right_outer = min(w, int(round(cx + outer_half)))
                roi[y, left_outer:left_inner] = True
                roi[y, right_inner:right_outer] = True

        guarded = candidate & roi

        if ndimage is not None:
            dilate_px = max(1, int(round(face_w * anchor_dilate_widths)))
            anchor_for_overlap = ndimage.binary_dilation(
                anchor, structure=np.ones((dilate_px, dilate_px))
            )

            labels, count = ndimage.label(guarded)
            if count > 0:
                keep = np.zeros_like(guarded, dtype=bool)
                for idx in range(1, count + 1):
                    component = labels == idx
                    if np.any(component & anchor_for_overlap):
                        keep |= component

                if not np.any(keep):
                    areas = np.bincount(labels.reshape(-1))
                    areas[0] = 0
                    keep = labels == areas.argmax()
                guarded = keep

        guarded = _trim_shoulder_base(guarded)
        guarded = _smooth_binary(guarded, close_pixels, remove_noise_pixels, feather_pixels)
        return guarded.astype(np.float32), roi.astype(np.float32)

    def execute(
        self,
        face_anchor_mask,
        candidate_mask,
        anchor_threshold,
        candidate_threshold,
        top_expand_face_heights,
        side_expand_face_widths,
        bottom_expand_face_heights,
        lower_taper_width,
        anchor_dilate_face_widths,
        close_pixels,
        remove_noise_pixels,
        feather_pixels,
    ):
        face_anchor_mask = _as_batch(face_anchor_mask).detach().cpu().float()
        candidate_mask = _as_batch(candidate_mask).detach().cpu().float()

        height, width = candidate_mask.shape[-2:]
        face_anchor_mask = _resize_mask(face_anchor_mask, height, width)

        batch = max(face_anchor_mask.shape[0], candidate_mask.shape[0])
        if face_anchor_mask.shape[0] < batch:
            face_anchor_mask = torch.cat(
                [face_anchor_mask, face_anchor_mask[-1:].repeat(batch - face_anchor_mask.shape[0], 1, 1)],
                dim=0,
            )
        if candidate_mask.shape[0] < batch:
            candidate_mask = torch.cat(
                [candidate_mask, candidate_mask[-1:].repeat(batch - candidate_mask.shape[0], 1, 1)],
                dim=0,
            )

        masks = []
        rois = []
        for idx in range(batch):
            guarded, roi = self._guard_one(
                face_anchor_mask[idx].numpy(),
                candidate_mask[idx].numpy(),
                anchor_threshold,
                candidate_threshold,
                top_expand_face_heights,
                side_expand_face_widths,
                bottom_expand_face_heights,
                lower_taper_width,
                anchor_dilate_face_widths,
                close_pixels,
                remove_noise_pixels,
                feather_pixels,
            )
            masks.append(torch.from_numpy(guarded))
            rois.append(torch.from_numpy(roi))

        return (torch.stack(masks, dim=0).float(), torch.stack(rois, dim=0).float())


NODE_CLASS_MAPPINGS = {
    "HumanHeadHairMaskGuard": HumanHeadHairMaskGuard,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HumanHeadHairMaskGuard": "Human Head+Hair Mask Guard",
}
