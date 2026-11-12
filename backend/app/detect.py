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
# Photos are resized so the longest side is this, up or down, before finding outlines.
# Big enough that the 1-2 pixel steps between fanned cards in a deck builder screenshot still show.
DETECT_SIZE = 2000
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
    if not single:
        best = best + card_sized_rectangles(blur, best)
    return reading_order([box / scale for box in best])[:MAX_CARDS]


# The rectangle search (see card_sized_rectangles).
SEARCH_SCALES = (0.9, 0.95, 1.0, 1.05, 1.1)  # card sizes tried, relative to the cards already found
SIDE_EDGE = 5  # pixels (at DETECT_SIZE): how far an edge may be off a rectangle's side and still back it
MIN_SIDE = 0.5  # share of every side that must lie on an edge
MIN_SIDES = 0.7  # share of all four sides, together, that must lie on edges
MAX_INNER_LINE = 0.85  # an edge running this much of a card's height inside it is another card's side
OVERLAP = 0.3  # a rectangle overlapping a card already found by this share of the smaller is the same card


def card_sized_rectangles(gray: np.ndarray, found: list[np.ndarray]) -> list[np.ndarray]:
    """More cards, found as rectangles of the size of those already found.

    Outlines break up when a photo is dim or sleeves catch the light, so some
    cards never give a closed outline. Their sides still show as straight edges, though, and
    every card in the photo is about the same size. So every place a rectangle of
    that size could sit is scored by how much of its four sides lies on edges
    running the same way (vertical for the left and right sides, horizontal for
    the top and bottom), the best-scoring places are kept, and any overlapping a
    card already found is dropped. A rectangle with an edge running down its
    middle straddles two cards, so it is dropped too.

    Needs two cards found already, to know the size and where the deck lies; a
    rectangle more than a card's size away from every card found is something
    else in the photo. Cards are taken to be upright.
    """
    if len(found) < 2:
        return []
    sides = sorted(sorted((np.linalg.norm(b[1] - b[0]), np.linalg.norm(b[2] - b[1]))) for b in found)
    width, height = float(np.median([s[0] for s in sides])), float(np.median([s[1] for s in sides]))

    edges = cv2.Canny(gray, 30, 100) > 0
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    vertical = (edges & (np.abs(gx) > np.abs(gy))).astype(np.uint8)
    horizontal = (edges & (np.abs(gy) >= np.abs(gx))).astype(np.uint8)
    vertical = cv2.dilate(vertical, np.ones((1, SIDE_EDGE), np.uint8)).astype(np.float32)
    horizontal = cv2.dilate(horizontal, np.ones((SIDE_EDGE, 1), np.uint8)).astype(np.float32)

    candidates = []
    h, w = gray.shape
    for size in SEARCH_SCALES:
        cw, ch = round(width * size), round(height * size)
        if cw >= w or ch >= h:
            continue
        # down[y, x]: share of the column x from row y down ch rows that is edge; across: of the row from x along cw.
        down = cv2.boxFilter(vertical, -1, (1, ch), anchor=(0, 0), borderType=cv2.BORDER_CONSTANT)
        across = cv2.boxFilter(horizontal, -1, (cw, 1), anchor=(0, 0), borderType=cv2.BORDER_CONSTANT)
        ny, nx = h - ch + 1, w - cw + 1  # top-left corners that keep the rectangle in the photo
        score = np.stack([
            down[:ny, :nx], down[:ny, cw - 1 : cw - 1 + nx],  # left, right
            across[:ny, :nx], across[ch - 1 : ch - 1 + ny, :nx],  # top, bottom
        ])
        total, weakest = score.mean(axis=0), score.min(axis=0)
        near = np.ones((max(3, ch // 4) | 1, max(3, cw // 4) | 1), np.uint8)
        best_nearby = total >= cv2.dilate(total, near)
        margin = round(cw * 0.12)
        for y, x in zip(*np.nonzero(best_nearby & (weakest >= MIN_SIDE) & (total >= MIN_SIDES))):
            if down[y, x + margin : x + cw - margin].max() < MAX_INNER_LINE:
                candidates.append((float(total[y, x]), (int(x), int(y), cw, ch)))

    taken = [cv2.boundingRect(b.astype(np.float32)) for b in found]
    candidates.sort(reverse=True)
    added: list[np.ndarray] = []
    while True:  # each card added can bring its neighbours within reach
        # The deck lies together, so a card is at most about a card away from the cards found;
        # further out are the photo's other things (a screenshot's buttons and logos).
        corners = np.concatenate(found + added)
        (left, top), (right, bottom) = corners.min(axis=0) - (width, height), corners.max(axis=0) + (width, height)
        before = len(added)
        for _, (x, y, cw, ch) in candidates:
            if not (left <= x + cw / 2 <= right and top <= y + ch / 2 <= bottom):
                continue
            if any(overlap_share((x, y, cw, ch), t) > OVERLAP for t in taken):
                continue
            taken.append((x, y, cw, ch))
            added.append(np.array([[x, y], [x + cw, y], [x + cw, y + ch], [x, y + ch]], dtype=np.float32))
        if len(added) == before:
            return added


def overlap_share(a, b) -> float:
    """How much two (x, y, w, h) rectangles overlap, as a share of the smaller."""
    ix = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    iy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(ix, 0) * max(iy, 0) / min(a[2] * a[3], b[2] * b[3])


def card_shapes(gray: np.ndarray, close: int, low: int, high: int, max_area: float = MAX_AREA) -> list[np.ndarray]:
    """Every outline in the picture that has a card's shape.

    A card running off the photo is rebuilt to its full size (see `complete`),
    so the box can reach past the photo's edge.
    """
    edges = cv2.Canny(gray, low, high)
    if close:
        # Close small gaps so each card's edge is one unbroken outline.
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((close, close), np.uint8))
    # RETR_LIST also returns outlines inside other outlines, e.g. cards inside a decklist panel.
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    support = cv2.dilate(edges, np.ones((5, 5), np.uint8))  # edges, give or take two pixels

    h, w = gray.shape[:2]
    photo_area = h * w
    found = []
    for contour in contours:
        contour = close_at_edge(contour, w, h)
        rect = cv2.minAreaRect(contour)
        rw, rh = rect[1]
        if min(rw, rh) < 1:
            continue
        # The outline should fill its rectangle (ignoring small dents where an edge was faint),
        # which rules out L-shapes and odd clusters.
        if cv2.contourArea(cv2.convexHull(contour)) < 0.85 * rw * rh:
            continue
        if rw * rh < MIN_IN_VIEW * MIN_AREA * photo_area:
            continue  # too small to hold a card, even with part of it off the photo
        box = complete(front_card(contour, rect, support), w, h)
        if box is None:
            continue
        rw, rh = np.linalg.norm(box[1] - box[0]), np.linalg.norm(box[2] - box[1])
        area = rw * rh
        if not MIN_AREA * photo_area <= area <= max_area * photo_area:
            continue
        if not RATIO_RANGE[0] <= max(rw, rh) / min(rw, rh) <= RATIO_RANGE[1]:
            continue
        found.append(box)
    return found


STEP_TOLERANCE = 2  # pixels (at DETECT_SIZE): how far off a side an outline's point can be and still be on it
MIN_FRONT = 0.4  # the front card of a stack is at least this share of the stack
MIN_BACKING = 0.7  # share of a front card's outline that must lie on edges in the photo


def front_card(contour: np.ndarray, rect, support: np.ndarray) -> np.ndarray:
    """The front card of a fanned stack, or the whole box when it's one card.

    A stack fanned out (sideways, or corner-wise as in deck builder screenshots)
    has an outline like a staircase, and its box takes in the strips of the
    cards behind. The front card shares two sides with the stack's box, meeting
    at one corner: its other corners are where the outline steps away from
    those sides. Each corner of the box gives a candidate this way. The ones
    kept are card-shaped, upright, and have their sides showing as edges in the
    photo. That still leaves the back card (its corner is as clean as the front
    card's), but the front card's side runs down inside the back card, so a
    candidate with an edge running its length inside it is dropped. Should that
    not settle it, the lowest and furthest right is taken, as cards are usually
    laid left to right.
    """
    box = cv2.boxPoints(rect)
    origin, u, v = box[0], box[1] - box[0], box[3] - box[0]
    lu, lv = float(np.linalg.norm(u)), float(np.linalg.norm(v))
    if lu < 1 or lv < 1:
        return box
    u, v = u / lu, v / lv
    pts = contour.reshape(-1, 2).astype(np.float32) - origin
    pu, pv = pts @ u, pts @ v

    def to_photo(u0: float, u1: float, v0: float, v1: float) -> np.ndarray:
        corners = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
        return np.array([origin + a * u + b * v for a, b in corners], dtype=np.float32)

    def backing(candidate: np.ndarray) -> float:
        """Share of the candidate's outline that lies on an edge in the photo."""
        t = np.linspace(0, 1, 24, endpoint=False)[:, None, None]
        ends = np.roll(candidate, -1, axis=0)
        xy = (candidate + t * (ends - candidate)).reshape(-1, 2).round().astype(int)
        h, w = support.shape
        inside = (xy[:, 0] >= 0) & (xy[:, 0] < w) & (xy[:, 1] >= 0) & (xy[:, 1] < h)
        xy = xy[inside]
        return float(support[xy[:, 1], xy[:, 0]].astype(bool).mean()) if len(xy) else 0.0

    candidates = [box]
    for cu in (0.0, lu):
        for cv in (0.0, lv):
            along_u = pu[np.abs(pv - cv) <= STEP_TOLERANCE]  # the outline's points on the side v = cv
            along_v = pv[np.abs(pu - cu) <= STEP_TOLERANCE]
            if not len(along_u) or not len(along_v):
                continue
            u0, u1 = (along_u.min(), lu) if cu else (0.0, along_u.max())
            v0, v1 = (along_v.min(), lv) if cv else (0.0, along_v.max())
            if (u1 - u0) * (v1 - v0) >= MIN_FRONT * lu * lv:
                candidates.append(to_photo(u0, u1, v0, v1))

    def peeled(c: np.ndarray) -> bool:
        """A card-shaped part of the box, standing upright, with its sides showing in the photo."""
        cu, cv = np.linalg.norm(c[1] - c[0]), np.linalg.norm(c[3] - c[0])
        if cu * cv > 0.9 * lu * lv:
            return False  # about the whole box
        if not RATIO_RANGE[0] <= max(cu, cv) / max(min(cu, cv), 1e-6) <= RATIO_RANGE[1]:
            return False
        width, height = c.max(axis=0) - c.min(axis=0)
        return height > width and backing(c) >= MIN_BACKING

    def crossed(c: np.ndarray) -> bool:
        """Whether an edge runs the card's length inside it: the side of a card lying on top of it."""
        a, b, d = c[0], c[1] - c[0], c[3] - c[0]
        if np.linalg.norm(b) > np.linalg.norm(d):
            b, d = d, b  # b across the card, d along it
        across = np.linspace(0.12, 0.88, max(2, int(np.linalg.norm(b) * 0.76)))
        along = np.linspace(0.0, 1.0, max(2, int(np.linalg.norm(d))))
        xy = (a + across[:, None, None] * b + along[None, :, None] * d).round().astype(int)
        h, w = support.shape
        xy[..., 0] = xy[..., 0].clip(0, w - 1)
        xy[..., 1] = xy[..., 1].clip(0, h - 1)
        return bool((support[xy[..., 1], xy[..., 0]] > 0).mean(axis=1).max() >= MAX_INNER_LINE)

    fronts = [c for c in candidates[1:] if peeled(c)]
    if not fronts:
        return box
    # A card behind has the front card's side running down inside it; the front card doesn't.
    fronts = [c for c in fronts if not crossed(c)] or fronts
    # If that leaves more than one: each card in a stack is laid on the one before, so the
    # front card is usually the last laid, the lowest and furthest right.
    return max(fronts, key=lambda c: float(c[:, 0].mean() + c[:, 1].mean()))


def close_at_edge(contour: np.ndarray, w: int, h: int) -> np.ndarray:
    """Closes an outline left open where it runs off the photo.

    Canny draws no line along the photo's own edge, so a card running off the photo
    has an outline open on that side, often with one of its sides broken off short
    too. Adding the points where the outline's span meets the photo's edge closes it,
    so it fills its rectangle like a whole card's outline does.
    """
    pts = contour.reshape(-1, 2)
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    extra = []
    if x0 <= EDGE_MARGIN:
        extra += [(0, y0), (0, y1)]
    if x1 >= w - 1 - EDGE_MARGIN:
        extra += [(w - 1, y0), (w - 1, y1)]
    if y0 <= EDGE_MARGIN:
        extra += [(x0, 0), (x1, 0)]
    if y1 >= h - 1 - EDGE_MARGIN:
        extra += [(x0, h - 1), (x1, h - 1)]
    if not extra:
        return contour
    return np.concatenate([pts, np.array(extra, dtype=pts.dtype)]).reshape(-1, 1, 2)


EDGE_MARGIN = 3  # pixels (at DETECT_SIZE): a box this close to the photo's edge is cut off by it
MIN_IN_VIEW = 0.4  # a card cut off by the photo's edge needs this share of it in the photo
SQUARE_TOLERANCE = 5  # degrees: how far a cut-off box may be turned from the photo's edges


def complete(box: np.ndarray, w: int, h: int) -> np.ndarray | None:
    """Rebuilds a card that runs off one edge of the photo to its full size.

    The visible part is too short for a card's shape, so it would fail the shape
    check. Its side along the photo's edge is whole, though, which gives the card's
    size: the box is stretched past the edge to a full card. The card is taken to be
    upright in the photo (as cards are usually laid out) unless the visible part is
    already deeper than an upright card would be, which means the card lies sideways.

    Boxes inside the photo come back as they are, as do boxes touching two or more
    edges or turned at an angle, since their full size can't be told. Returns None
    for a sliver too small to be a card.
    """
    x0, y0 = box.min(axis=0)
    x1, y1 = box.max(axis=0)
    cut = {
        "left": x0 <= EDGE_MARGIN,
        "right": x1 >= w - 1 - EDGE_MARGIN,
        "top": y0 <= EDGE_MARGIN,
        "bottom": y1 >= h - 1 - EDGE_MARGIN,
    }
    sides = [side for side, hit in cut.items() if hit]
    if len(sides) != 1:
        return box
    side = sides[0]
    angle = np.degrees(np.arctan2(*(box[1] - box[0])[::-1])) % 90
    if min(angle, 90 - angle) > SQUARE_TOLERANCE:
        return box

    horizontal = side in ("top", "bottom")  # the photo's edge the card runs off
    along, depth = (x1 - x0, y1 - y0) if horizontal else (y1 - y0, x1 - x0)
    # Along a top or bottom edge an upright card shows its width; along a side edge, its height.
    upright, sideways = (along * CARD_RATIO, along / CARD_RATIO) if horizontal else (along / CARD_RATIO, along * CARD_RATIO)
    full = upright if upright >= depth * 0.97 else sideways
    if full < depth * 0.97:
        return box  # deeper than any card this wide: not a cut-off card, leave it to the shape check
    if depth / full < MIN_IN_VIEW:
        return None
    full = max(full, depth)
    if side == "left":
        x0 = x1 - full
    elif side == "right":
        x1 = x0 + full
    elif side == "top":
        y0 = y1 - full
    else:
        y1 = y0 + full
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)


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
