"""Compare real inference presets and trackers against reviewed local reference frames.

Usage: python -m scripts.benchmark_analysis dataset.json --output .e2e-live/benchmark/results
Frames must be manually reviewed. Empty labels are deliberate negative frames.
Model predictions are never treated as ground truth. No video is uploaded.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import time

import cv2

from app.inference.benchmark import evaluate_frames, evaluate_tracking, evaluate_events
from app.inference.advanced_tracker import make_tracker
from app.inference.options import resolve_options
from app.inference import worker
from app.rules.engine import CameraRuleEngine


def percentile(values, p):
    return sorted(values)[min(len(values)-1,round((len(values)-1)*p))] if values else None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--presets",default="fast,balanced,detail,tiled,focused")
    parser.add_argument("--trackers",default="centroid,bytetrack,botsort")
    parser.add_argument("--split",choices=["development","test","all"],default="test")
    parser.add_argument("--fast-model",default="yolov8n.pt")
    parser.add_argument("--detail-model",default="yolov8s.pt")
    parser.add_argument("--device",default="cpu",help="cpu, cuda, or a local accelerator device")
    args=parser.parse_args()
    dataset=json.loads(args.dataset.read_text(encoding="utf-8-sig"))
    frames=[f for f in dataset["frames"] if f.get("reviewed") is True and (args.split=="all" or f.get("split","development")==args.split)]
    if not frames:
        parser.error("No reviewed frames in the selected split. Label frames first; predictions are not labels.")
    for frame in frames:
        if "labels" not in frame:
            parser.error("Every reviewed frame must have a labels list, including negative examples")
        for label in frame["labels"]:
            box=label.get("bbox",[])
            if len(box)!=4 or not all(0<=x<=1 for x in box) or box[0]>=box[2] or box[1]>=box[3]:
                parser.error("Labels require ordered normalized xyxy boxes")
    # Train/development/test must split by sequence/source, never adjacent frames.
    splits={}
    for frame in dataset["frames"]:
        splits.setdefault(frame.get("source_id",frame.get("sequence",frame["image"])),set()).add(frame.get("split","development"))
    if any(len(v)>1 for v in splits.values()):
        parser.error("A sequence appears in more than one split; this leaks neighboring frames into evaluation")
    frames.sort(key=lambda f:(f.get("sequence",f["image"]),f.get("timestamp",1)))
    args.output.mkdir(parents=True,exist_ok=True)
    os.environ["YOLO_MODEL"]=args.fast_model
    os.environ["YOLO_DETAIL_MODEL"]=args.detail_model
    from app.config import get_settings
    get_settings.cache_clear()
    started=time.perf_counter()
    worker.init_worker(args.fast_model,args.device,.35,.35,640)
    report={"frames":len(frames),"split":args.split,"device":args.device,"classes":dataset.get("classes",["person"]),
            "warmup_seconds":time.perf_counter()-started,"profiles":{},
            "limitations":["Small manually labeled sets are development evidence, not production accuracy guarantees.",
                           "Use independent clips from each actual camera before selecting production thresholds."]}
    encoded=[]
    for frame in frames:
        path=(args.dataset.parent/frame["image"]).resolve()
        if args.dataset.parent.resolve() not in path.parents:
            parser.error("Frame paths must stay inside the dataset directory")
        image=cv2.imread(str(path))
        if image is None:
            parser.error(f"Cannot read {frame['image']}")
        encoded.append(cv2.imencode(".jpg",image)[1].tobytes())
    for preset in args.presets.split(","):
        options=resolve_options({"preset":"balanced" if preset=="tiled" else "fast" if preset=="focused" else preset,"tiled":preset=="tiled", "tracker":"bytetrack"})
        # First call includes model loading; keep it separate from steady-state timing.
        t=time.perf_counter(); worker.detect_batch([encoded[0]],[options]); warm=time.perf_counter()-t
        predictions=[]; timings=[]
        for frame,buf in zip(frames,encoded):
            frame_options={**options,"regions":frame.get("detail_regions",[])} if preset=="focused" else options
            t=time.perf_counter(); prediction=worker.detect_batch([buf],[frame_options])[0]
            timings.append(time.perf_counter()-t); predictions.append(prediction)
        result=evaluate_frames(frames,predictions,report["classes"])
        result["confidence_sweep"]={}
        if args.split=="development":
            for confidence in [.2,.3,.35,.4,.5,.6,.7]:
                filtered=[[{**p,"confirmed":p["confidence"]>=confidence} for p in row] for row in predictions]
                measured=evaluate_frames(frames,filtered,report["classes"])
                measured["f1"]=2*measured["tp"]/(2*measured["tp"]+measured["fp"]+measured["fn"]) if measured["tp"] else 0
                result["confidence_sweep"][str(confidence)]=measured
        result.update({"model":options["model"],"input_size":options["input_size"],"model_start_seconds":warm,
            "inference_ms_p50":1000*percentile(timings,.5),"inference_ms_p95":1000*percentile(timings,.95),
            "inference_fps":len(timings)/sum(timings),"trackers":{},"scenarios":{}})
        for scenario in sorted({f.get("scenario","unspecified") for f in frames}):
            indices=[i for i,f in enumerate(frames) if f.get("scenario","unspecified")==scenario]
            result["scenarios"][scenario]=evaluate_frames([frames[i] for i in indices],[predictions[i] for i in indices],report["classes"])
        for tracker in args.trackers.split(","):
            result["trackers"][tracker]=evaluate_tracking(frames,predictions,lambda:make_tracker({**options,"tracker":tracker}))
            if dataset.get("events"):
                observed=[]; engines={}; trackers={}
                for frame,preds in zip(frames,predictions):
                    sequence=frame.get("sequence",frame["image"])
                    if sequence not in trackers:
                        trackers[sequence]=make_tracker({**options,"tracker":tracker})
                        engines[sequence]=CameraRuleEngine(sequence,dataset.get("zones",[]),dataset.get("rules",[]),3)
                    ts=frame.get("timestamp",1.)
                    tracks=trackers[sequence].update([dict(p) for p in preds],now=ts)
                    fires=engines[sequence].evaluate([t for t in tracks if t is not None],now=ts)
                    observed.extend({"timestamp":ts,"type":f.incident_type,"rule_id":f.rule_id,"sequence":sequence} for f in fires)
                sequences={f.get("sequence",f["image"]) for f in frames}
                expected=[e for e in dataset["events"] if e.get("sequence") in sequences or e.get("sequence") is None]
                result["trackers"][tracker]["events"]=evaluate_events(expected,observed)
        report["profiles"][preset]=result
        (args.output/f"{preset}-predictions.json").write_text(json.dumps(predictions,indent=2),encoding="utf-8")
        print(json.dumps({"profile":preset,"precision":result["precision"],"recall":result["recall"],"map50":result["map50"],"fps":result["inference_fps"]}),flush=True)
    (args.output/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    lines=["# Analysis benchmark", "",f"Reviewed frames: {len(frames)}; split: {args.split}. Ground truth must be independently reviewed.","",
           "| Profile | Precision | Recall | mAP50 | FPS | p95 ms |", "|---|---:|---:|---:|---:|---:|"]
    for name,r in report["profiles"].items():
        fmt=lambda v: "N/A" if v is None else f"{v:.3f}"
        lines.append(f"| {name} | {fmt(r['precision'])} | {fmt(r['recall'])} | {fmt(r['map50'])} | {fmt(r['inference_fps'])} | {fmt(r['inference_ms_p95'])} |")
    lines += ["",*report["limitations"]]
    (args.output/"report.md").write_text("\n".join(lines),encoding="utf-8")


if __name__=="__main__":
    main()
