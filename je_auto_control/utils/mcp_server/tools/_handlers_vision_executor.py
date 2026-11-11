"""MCP vision adapters delegating lazily to executor commands.

Annotations mirror the executor JSON boundary, including heterogeneous payloads.
"""

from typing import Any, Dict, List, Optional


def grid_cell(boxes: Any, row: Any, col: Any, row_tolerance: Any = 10, box_format: str = "xywh") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _grid_cell

    return _grid_cell(boxes, row, col, row_tolerance, box_format)


def match_template(
    template: str, min_score: Any = 0.8, scales: Any = None, region: Any = None, method: str = "ccoeff_normed"
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_template

    return _match_template(template, min_score, scales, region, method)


def match_template_all(
    template: str, min_score: Any = 0.8, max_results: Any = 20, nms_iou: Any = 0.3, region: Any = None
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_template_all

    return _match_template_all(template, min_score, max_results, nms_iou, region)


def match_masked(template: str, mask: Any = None, min_score: Any = 0.9, region: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_masked

    return _match_masked(template, mask, min_score, region)


def match_masked_all(
    template: str, mask: Any = None, min_score: Any = 0.9, max_results: Any = 20, nms_iou: Any = 0.3, region: Any = None
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_masked_all

    return _match_masked_all(template, mask, min_score, max_results, nms_iou, region)


def match_rotated(
    template: str,
    min_score: Any = 0.8,
    scales: Any = None,
    angles: Any = None,
    region: Any = None,
    method: str = "ccoeff_normed",
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_rotated

    return _match_rotated(template, min_score, scales, angles, region, method)


def match_rotated_all(
    template: str,
    min_score: Any = 0.8,
    scales: Any = None,
    angles: Any = None,
    max_results: Any = 20,
    nms_iou: Any = 0.3,
    region: Any = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_rotated_all

    return _match_rotated_all(template, min_score, scales, angles, max_results, nms_iou, region)


def match_with_trust(
    template: str,
    min_score: Any = 0.0,
    scales: Any = None,
    ambiguous_ratio: Any = 0.9,
    region: Any = None,
    method: str = "ccoeff_normed",
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_with_trust

    return _match_with_trust(template, min_score, scales, ambiguous_ratio, region, method)


def auto_threshold(template: str, region: Any = None, method: str = "ccoeff_normed") -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _auto_threshold

    return _auto_threshold(template, region, method)


def match_auto(
    template: str, floor: Any = 0.5, max_results: Any = 20, region: Any = None, method: str = "ccoeff_normed"
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_auto

    return _match_auto(template, floor, max_results, region, method)


def edge_match(template: str, min_score: Any = 0.7, scales: Any = None, region: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _edge_match

    return _edge_match(template, min_score, scales, region)


def edge_match_all(
    template: str, min_score: Any = 0.7, max_results: Any = 20, nms_iou: Any = 0.3, region: Any = None
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _edge_match_all

    return _edge_match_all(template, min_score, max_results, nms_iou, region)


def match_subpixel(
    template: str, min_score: Any = 0.0, region: Any = None, method: str = "ccoeff_normed"
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_subpixel

    return _match_subpixel(template, min_score, region, method)


def vote_centers(centers: Any, agree_px: Any = 10, min_votes: Any = 2) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _vote_centers

    return _vote_centers(centers, agree_px, min_votes)


def match_ensemble(
    templates: Any, min_score: Any = 0.8, agree_px: Any = 10, min_votes: Any = 2, region: Any = None
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_ensemble

    return _match_ensemble(templates, min_score, agree_px, min_votes, region)


def match_color(
    template: str, channels: Any = None, min_score: Any = 0.7, scales: Any = None, region: Any = None
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_color

    return _match_color(template, channels, min_score, scales, region)


def match_color_all(
    template: str,
    channels: Any = None,
    min_score: Any = 0.7,
    max_results: Any = 20,
    nms_iou: Any = 0.3,
    region: Any = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_color_all

    return _match_color_all(template, channels, min_score, max_results, nms_iou, region)


def region_stability(frames: Any, settle_threshold: Any = 0.99) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _region_stability

    return _region_stability(frames, settle_threshold)


def match_persistence(template: str, frames: Any, min_score: Any = 0.8, agree_px: Any = 8) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_persistence

    return _match_persistence(template, frames, min_score, agree_px)


def grid_cells(rows: Any, cols: Any, region: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _grid_cells

    return _grid_cells(rows, cols, region)


def cell_for_point(x: Any, y: Any, rows: Any, cols: Any, region: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _cell_for_point

    return _cell_for_point(x, y, rows, cols, region)


def point_for_cell(label: str, rows: Any, cols: Any, region: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _point_for_cell

    return _point_for_cell(label, rows, cols, region)


def populate_table(grid: Any, text_boxes: Any, overlap: Any = 0.4) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _populate_table

    return _populate_table(grid, text_boxes, overlap)


def column_gutters(boxes: Any, page_width: Any = None, min_gap: Any = 8) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _column_gutters

    return _column_gutters(boxes, page_width, min_gap)


def detect_borderless_table(
    boxes: Any, page_width: Any = None, min_gap: Any = 8, min_cols: Any = 2, min_rows: Any = 2
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _detect_borderless_table

    return _detect_borderless_table(boxes, page_width, min_gap, min_cols, min_rows)


def associate_fields(text_boxes: Any, directions: Any = None, max_gap: Any = 150) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _associate_fields

    return _associate_fields(text_boxes, directions, max_gap)


def match_labels_to_widgets(labels: Any, widgets: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _match_labels_to_widgets

    return _match_labels_to_widgets(labels, widgets)


def flow_order(boxes: Any, min_gap: Any = 12) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _flow_order

    return _flow_order(boxes, min_gap)


def xy_cut(boxes: Any, min_gap: Any = 12) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _xy_cut

    return _xy_cut(boxes, min_gap)


def group_paragraphs(lines: Any, line_gap_factor: Any = 1.6) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _group_paragraphs

    return _group_paragraphs(lines, line_gap_factor)


def detect_lists(lines: Any) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _detect_lists

    return _detect_lists(lines)


def classify_lines(lines: Any, heading_ratio: Any = 1.2) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _classify_lines

    return _classify_lines(lines, heading_ratio)


def outline(lines: Any, heading_ratio: Any = 1.2) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _outline

    return _outline(lines, heading_ratio)


def find_color_region(rgb: Any, tolerance: Any = 20, min_area: Any = 50, region: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _find_color_region

    return _find_color_region(rgb, tolerance, min_area, region)


def ssim_compare(reference: str, current: Any = None, ignore: Any = None, region: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _ssim_compare

    return _ssim_compare(reference, current, ignore, region)


def ssim_changed_regions(
    reference: str,
    current: Any = None,
    ignore: Any = None,
    threshold: Any = 0.35,
    min_area: Any = 50,
    region: Any = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _ssim_changed_regions

    return _ssim_changed_regions(reference, current, ignore, threshold, min_area, region)


def feature_match(
    template: str, region: Any = None, max_features: Any = 500, ratio: Any = 0.75, min_inliers: Any = 10
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _feature_match

    return _feature_match(template, region, max_features, ratio, min_inliers)


def find_shapes(region: Any = None, min_area: Any = 400, max_area: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _find_shapes

    return _find_shapes(region, min_area, max_area)


def find_rectangles(
    region: Any = None, min_area: Any = 400, max_area: Any = None, aspect_range: Any = None, epsilon: Any = 0.04
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _find_rectangles

    return _find_rectangles(region, min_area, max_area, aspect_range, epsilon)


def preprocess_image(
    output_path: str,
    source: Any = None,
    steps: Any = None,
    scale: Any = 2.0,
    region: Any = None,
    block_size: Any = 31,
    c: Any = 11,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _preprocess_image

    return _preprocess_image(output_path, source, steps, scale, region, block_size, c)


def wait_actionable(
    template: str, timeout_s: Any = 5.0, stable_for_s: Any = 0.3, min_score: Any = 0.8, region: Any = None
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _wait_actionable

    return _wait_actionable(template, timeout_s, stable_for_s, min_score, region)


def fuse_elements(ocr: Any = None, icon: Any = None, a11y: Any = None, iou_threshold: Any = 0.9) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _fuse_elements

    return _fuse_elements(ocr, icon, a11y, iou_threshold)


def reading_order(elements: Any, row_tol: Any = 12) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _reading_order

    return _reading_order(elements, row_tol)


def segment_hsv(lower_hsv: Any, upper_hsv: Any, min_area: Any = 50, region: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _segment_hsv

    return _segment_hsv(lower_hsv, upper_hsv, min_area, region)


def dominant_hue_regions(
    hue: Any, hue_tol: Any = 10, sat_min: Any = 80, val_min: Any = 80, min_area: Any = 50, region: Any = None
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _dominant_hue_regions

    return _dominant_hue_regions(hue, hue_tol, sat_min, val_min, min_area, region)


def find_text_regions(
    min_area: Any = 60, max_area: Any = None, merge: Any = True, max_aspect: Any = 12.0, region: Any = None
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _find_text_regions

    return _find_text_regions(min_area, max_area, merge, max_aspect, region)


def find_text_lines(y_tolerance: Any = 8, region: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _find_text_lines

    return _find_text_lines(y_tolerance, region)


def find_lines(min_length: Any = 80, max_gap: Any = 10, orientation: str = "any", region: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _find_lines

    return _find_lines(min_length, max_gap, orientation, region)


def find_grid(min_length: Any = 120, tol: Any = 10, region: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _find_grid

    return _find_grid(min_length, tol, region)


def find_separators(
    axis: str = "horizontal", min_length: Any = 120, tol: Any = 10, region: Any = None
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _find_separators

    return _find_separators(axis, min_length, tol, region)


def locate_chain(boxes: Any, ops: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _locate_chain

    return _locate_chain(boxes, ops)


def image_quality(source: Any = None, region: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _image_quality

    return _image_quality(source, region)


def quality_gate(
    source: Any = None, region: Any = None, min_sharpness: Any = 100.0, min_contrast: Any = 12.0
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _quality_gate

    return _quality_gate(source, region, min_sharpness, min_contrast)


def detect_scale(
    template: Any, haystack: Any = None, region: Any = None, scales: Any = None, method: str = "ccoeff_normed"
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _detect_scale

    return _detect_scale(template, haystack, region, scales, method)


def scale_sweep(
    template: Any, haystack: Any = None, region: Any = None, scales: Any = None, method: str = "ccoeff_normed"
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _scale_sweep

    return _scale_sweep(template, haystack, region, scales, method)


def salient_regions(
    source: Any = None, region: Any = None, size: Any = 64, threshold: Any = None, min_area: Any = 4
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _salient_regions

    return _salient_regions(source, region, size, threshold, min_area)


def most_salient(
    source: Any = None, region: Any = None, size: Any = 64, threshold: Any = None, min_area: Any = 4
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _most_salient

    return _most_salient(source, region, size, threshold, min_area)


def image_histogram(source: Any = None, bins: Any = 32, space: str = "hsv", region: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _image_histogram

    return _image_histogram(source, bins, space, region)


def histogram_changed(
    reference: str,
    current: Any = None,
    method: str = "correlation",
    threshold: Any = 0.9,
    space: str = "hsv",
    region: Any = None,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _histogram_changed

    return _histogram_changed(reference, current, method, threshold, space, region)


def changed_regions(
    before: str, after: Any = None, threshold: Any = 25, min_area: Any = 80, blur: Any = 5
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _changed_regions

    return _changed_regions(before, after, threshold, min_area, blur)


def has_motion(before: str, after: Any = None, threshold: Any = 25, min_area: Any = 80) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _has_motion

    return _has_motion(before, after, threshold, min_area)


def perceptual_diff(
    actual: str, expected: str, threshold: Any = 0.1, include_aa: Any = False, max_diff_ratio: Any = None
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _perceptual_diff

    return _perceptual_diff(actual, expected, threshold, include_aa, max_diff_ratio)


def read_barcodes(source: Any = None, region: Any = None) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _read_barcodes

    return _read_barcodes(source, region)


def wait_image_gone(
    image: Any,
    detect_threshold: float = 1.0,
    timeout_s: float = 10.0,
    poll_interval_s: float = 0.2,
    gone_for_s: float = 0.0,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _wait_image_gone

    return _wait_image_gone(image, detect_threshold, timeout_s, poll_interval_s, gone_for_s)


def wait_text_gone(
    text: str, timeout_s: float = 10.0, poll_interval_s: float = 0.2, gone_for_s: float = 0.0
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _wait_text_gone

    return _wait_text_gone(text, timeout_s, poll_interval_s, gone_for_s)


def wait_color(
    target_rgb: Any,
    region: Any = None,
    tolerance: int = 10,
    min_fraction: float = 0.5,
    present: bool = True,
    timeout_s: float = 10.0,
    poll_interval_s: float = 0.2,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _wait_color

    return _wait_color(target_rgb, region, tolerance, min_fraction, present, timeout_s, poll_interval_s)


def wait_window_title(
    pattern: str, present: bool = True, regex: bool = True, timeout_s: float = 10.0, poll_interval_s: float = 0.2
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _wait_window_title

    return _wait_window_title(pattern, present, regex, timeout_s, poll_interval_s)


def anchor_locate(
    anchor: Dict[str, Any],
    target: Dict[str, Any],
    relation: str = "near",
    max_distance_px: float = 200.0,
    ordinal: int = 1,
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _anchor_locate

    return _anchor_locate(anchor, target, relation, max_distance_px, ordinal)


def anchor_locate_all(
    anchor: Dict[str, Any], target: Dict[str, Any], relation: str = "near", max_distance_px: float = 200.0
) -> Dict[str, Any]:
    from je_auto_control.utils.executor.action_executor import _anchor_locate_all

    return _anchor_locate_all(anchor, target, relation, max_distance_px)


def redact_screenshot(
    file_path: str,
    output_path: Optional[str] = None,
    policy: str = "moderate",
    regions: Optional[List[List[int]]] = None,
    accessibility: Optional[List[Dict[str, Any]]] = None,
    ocr: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Blur PII regions in a saved screenshot via the redaction engine."""
    from je_auto_control.utils.executor.action_executor import (
        _redact_screenshot,
    )

    return _redact_screenshot(
        file_path=file_path,
        output_path=output_path,
        policy=policy,
        regions=regions,
        accessibility=accessibility,
        ocr=ocr,
    )
