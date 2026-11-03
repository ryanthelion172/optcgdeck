"""Finds the cards in a photo with OpenCV and cuts each one out.

Works best when the cards lie flat, don't overlap, and sit on a plain
background that contrasts with them. Each card's outline is found, checked
for a card's shape (63 x 88 mm, so about 1.4 times taller than wide), then
straightened and cropped so it can be identified on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

CARD_RATIO = 88 / 63
RATIO_RANGE = (1.2, 1.6)  # allows for photos taken a little off straight-on
MIN_AREA = 0.002  # smallest card, as a share of the photo
MAX_AREA = 0.9
SINGLE_MAX_AREA = 0.98  # a photo of one card can be almost all card
DETECT_SIZE = 1200  # photos are resized so the longest side is this, up or down, before finding outlines
CROP_SIZE = (630, 880)  # width, height of each cropped card
MAX_CARDS = 60


@dataclass
class FoundCard:
    jpeg: bytes
    # Corners in the original photo, as fractions of its width and height
    # (top-left, top-right, bottom-right, bottom-left of the card as cropped).
    corners: list[list[float]]


class BadImage(ValueError):
    pass


def decode(image: bytes) -> np.ndarray:
    # IMREAD_COLOR also applies the photo's EXIF rotation, so phone photos come out upright.
    img = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise BadImage("That file isn't an image we can read.")
    return img


# Edge settings tried on every photo: (gap-closing size, Canny low, Canny high).
# Cards packed tightly need little gap closing; faint or busy photos need more.
VARIANTS = [(0, 50, 150), (3, 50, 150), (3, 30, 100), (5, 50, 150), (5, 30, 100)]


def find_outlines(img: np.ndarray, single: bool = False) -> list[np.ndarray]:
    """Returns each card's four corners (in `img` pixels), in reading order.

    Edge detection is run with a few settings and the one that finds the most
    cards of a similar size wins, since no single setting suits every photo. On
    a tie the larger boxes win, since a faint outer edge loses to the card's
    inner frame with some settings.

    With `single`, the photo holds one card: the biggest card-shaped outline is
    returned on its own, and it may fill nearly the whole photo.
    """
    h, w = img.shape[:2]
    # A fixed working size keeps edge widths and gaps between cards comparable for any photo.
    scale = DETECT_SIZE / max(h, w)
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    small = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=interpolation)
    blur = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)

    max_area = SINGLE_MAX_AREA if single else MAX_AREA
    best: list[np.ndarray] = []
    best_key = (0, 0.0)
    for close, low, high in VARIANTS:
        boxes = card_shapes(blur, close, low, high, max_area)
        if single:
            boxes = sorted(boxes, key=cv2.contourArea)[-1:]
        else:
            boxes = similar_size(drop_nested(boxes))
        key = (len(boxes), sum(cv2.contourArea(b) for b in boxes))
        if key > best_key:
            best, best_key = boxes, key
    return reading_order([box / scale for box in best])[:MAX_CARDS]


def card_shapes(gray: np.ndarray, close: int, low: int, high: int, max_area: float = MAX_AREA) -> list[np.ndarray]:
    """Every outline in the picture that has a card's shape."""
    edges = cv2.Canny(gray, low, high)
    if close:
        # Close small gaps so each card's edge is one unbroken outline.
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((close, close), np.uint8))
    # RETR_LIST also returns outlines inside other outlines, e.g. cards inside a decklist panel.
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    photo_area = gray.shape[0] * gray.shape[1]
    found = []
    for contour in contours:
        rect = cv2.minAreaRect(contour)
        rw, rh = rect[1]
        if min(rw, rh) < 1:
            continue
        area = rw * rh
        if not MIN_AREA * photo_area <= area <= max_area * photo_area:
            continue
        if not RATIO_RANGE[0] <= max(rw, rh) / min(rw, rh) <= RATIO_RANGE[1]:
            continue
        # The outline should fill its rectangle (ignoring small dents where an edge was faint),
        # which rules out L-shapes and odd clusters.
        if cv2.contourArea(cv2.convexHull(contour)) < 0.85 * area:
            continue
        found.append(cv2.boxPoints(rect))
    return found


def similar_size(boxes: list[np.ndarray]) -> list[np.ndarray]:
    """Cards in one photo are about the same size; drops boxes far from the typical one."""
    if len(boxes) < 3:
        return boxes
    typical = float(np.median([cv2.contourArea(b) for b in boxes]))
    return [b for b in boxes if 0.5 * typical <= cv2.contourArea(b) <= 2 * typical]


def reading_order(boxes: list[np.ndarray]) -> list[np.ndarray]:
    """Top to bottom by row, then left to right, so results follow the layout."""
    if not boxes:
        return boxes
    by_y = sorted(boxes, key=lambda b: b[:, 1].mean())
    half_card = float(np.median([b[:, 1].max() - b[:, 1].min() for b in boxes])) / 2
    rows, row = [], [by_y[0]]
    for box in by_y[1:]:
        if box[:, 1].mean() - row[-1][:, 1].mean() > half_card:
            rows.append(row)
            row = []
        row.append(box)
    rows.append(row)
    return [box for r in rows for box in sorted(r, key=lambda b: b[:, 0].mean())]


def same_place(a: np.ndarray, b: np.ndarray) -> bool:
    area_a, area_b = cv2.contourArea(a), cv2.contourArea(b)
    close = np.linalg.norm(a.mean(axis=0) - b.mean(axis=0)) < 0.1 * np.sqrt(max(area_a, area_b))
    return close and 0.8 <= area_a / max(area_b, 1e-6) <= 1.25


def drop_nested(boxes: list[np.ndarray]) -> list[np.ndarray]:
    """Keeps one box per card.

    A box holding two or more other boxes is a panel or table around the cards, so
    it goes. Of the boxes left, one inside another is the card's art or inner
    frame (or the inside edge of the same outline), so only the outer one stays.
    """
    # The inside and outside edges of one outline give two near-identical boxes; keep one.
    unique: list[np.ndarray] = []
    for box in sorted(boxes, key=cv2.contourArea, reverse=True):
        if not any(same_place(box, u) for u in unique):
            unique.append(box)
    boxes = unique

    def inside(inner: np.ndarray, outer: np.ndarray) -> bool:
        cx, cy = inner.mean(axis=0)
        return cv2.pointPolygonTest(outer.astype(np.float32), (float(cx), float(cy)), False) >= 0 and (
            cv2.contourArea(inner) < cv2.contourArea(outer)
        )

    def separate(group: list[np.ndarray]) -> int:
        """How many boxes in the group don't sit inside another one in the group."""
        return sum(not any(inside(b, o) for o in group if o is not b) for b in group)

    kept = []
    for box in boxes:
        children = [b for b in boxes if b is not box and inside(b, box)]
        if separate(children) < 2:  # not a container of several cards
            kept.append(box)
    return [b for b in kept if not any(inside(b, o) for o in kept if o is not b)]


def order_corners(box: np.ndarray) -> np.ndarray:
    """Top-left, top-right, bottom-right, bottom-left, with the card standing upright.

    A sideways card gets turned a quarter. Which way up it ends is a guess; the
    identifier copes with upside-down cards.
    """
    pts = box.astype(np.float32)
    first, second = pts[1] - pts[0], pts[2] - pts[1]
    if first[0] * second[1] - first[1] * second[0] < 0:  # make the order clockwise on screen
        pts = pts[::-1].copy()
    best = None
    for i in range(4):
        p = np.roll(pts, -i, axis=0)
        top, side = np.linalg.norm(p[1] - p[0]), np.linalg.norm(p[3] - p[0])
        if top > side:
            continue  # the top edge must be a short edge
        height = p[0][1] + p[1][1]  # prefer the short edge that is higher in the photo
        if best is None or height < best[0]:
            best = (height, p)
    return best[1]


def crop(img: np.ndarray, corners: np.ndarray) -> np.ndarray:
    cw, ch = CROP_SIZE
    target = np.array([[0, 0], [cw - 1, 0], [cw - 1, ch - 1], [0, ch - 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(corners, target)
    return cv2.warpPerspective(img, matrix, (cw, ch))


def find_cards(image: bytes, single: bool = False) -> list[FoundCard]:
    """Crops each card in the photo. With `single`, at most one: the photo is of one card."""
    img = decode(image)
    h, w = img.shape[:2]
    cards = []
    for box in find_outlines(img, single):
        corners = order_corners(box)
        ok, jpeg = cv2.imencode(".jpg", crop(img, corners), [cv2.IMWRITE_JPEG_QUALITY, 90])
        if ok:
            fractions = [[round(float(x) / w, 4), round(float(y) / h, 4)] for x, y in corners]
            cards.append(FoundCard(jpeg=jpeg.tobytes(), corners=fractions))
    return cards
