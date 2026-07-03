"""Run RF-DETR inference on a video file using line parameters from sources.json."""
import argparse
import sys
import os

import cv2
import supervision as sv
from rfdetr import RFDETRNano

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config_manager.ConfigManager import ConfigManager


def build_linezones(config_path: str, width: int, height: int) -> dict[str, sv.LineZone]:
    cm = ConfigManager(sources_config_path=config_path)
    line_dict = cm.lines.line_manager.to_dict()
    zones = {}
    for line_id, cfg in line_dict.items():
        pt = cfg["point_list"]
        start = sv.Point(x=int(pt[0][0] * width), y=int(pt[0][1] * height))
        end   = sv.Point(x=int(pt[1][0] * width), y=int(pt[1][1] * height))
        zones[line_id] = sv.LineZone(
            start=start,
            end=end,
            triggering_anchors=[sv.Position.CENTER],
            minimum_crossing_threshold=1,
        )
        print(f"  line '{cfg['name']}' ({line_id}): {start} → {end}")
    return zones


def main():
    parser = argparse.ArgumentParser(description="RF-DETR line-crossing count on a video file")
    parser.add_argument("input",  help="Input video file path")
    parser.add_argument("output", help="Output annotated video file path")
    parser.add_argument("--config",     default="config/sources.json",              help="Path to sources.json")
    parser.add_argument("--weights",    default="checkpoint_best_total.pth",        help="Model checkpoint path")
    parser.add_argument("--threshold",  type=float, default=0.5,                    help="Detection confidence threshold")
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.input)
    if not cap.isOpened():
        sys.exit(f"Cannot open video: {args.input}")

    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"Video: {width}x{height} @ {fps:.1f} fps  ({total} frames)")

    print("Loading line zones from config...")
    zones = build_linezones(args.config, width, height)
    if not zones:
        sys.exit("No lines found in config — add a line via the API first.")

    print(f"Loading model from {args.weights}...")
    model   = RFDETRNano(pretrain_weights=args.weights)
    tracker = sv.ByteTrack()

    box_annotator   = sv.BoxAnnotator(thickness=2)
    trace_annotator = sv.TraceAnnotator(thickness=2)
    zone_annotator  = sv.LineZoneAnnotator(thickness=2, text_thickness=2, text_scale=1)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(args.output, fourcc, fps, (width, height))

    frame_idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            detections = model.predict(frame, threshold=args.threshold)
            detections = tracker.update_with_detections(detections)

            for zone in zones.values():
                zone.trigger(detections)

            annotated = frame.copy()
            for zone in zones.values():
                annotated = zone_annotator.annotate(annotated, line_counter=zone)
            annotated = trace_annotator.annotate(scene=annotated, detections=detections)
            annotated = box_annotator.annotate(scene=annotated, detections=detections)

            writer.write(annotated)
            frame_idx += 1
            if frame_idx % 100 == 0:
                counts = {cfg_id: {"in": z.in_count, "out": z.out_count} for cfg_id, z in zones.items()}
                print(f"  frame {frame_idx}/{total}  counts={counts}")

    finally:
        cap.release()
        writer.release()

    print(f"\nDone — {frame_idx} frames written to {args.output}")
    for line_id, z in zones.items():
        print(f"  {line_id}: in={z.in_count}  out={z.out_count}")


if __name__ == "__main__":
    main()
