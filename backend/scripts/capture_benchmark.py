"""Save reference frames for manual labeling. No model-generated ground truth."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import cv2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--scenario",choices=["day","night","crowded","blurred","other"],required=True)
    parser.add_argument("--frames",type=int,default=6)
    parser.add_argument("--stride",type=int,default=15)
    parser.add_argument("--blur",action="store_true",help="Create explicitly marked synthetic blur samples")
    args=parser.parse_args()
    if args.frames<1 or args.stride<1:
        parser.error("frames and stride must be positive")
    source=args.source
    if source.startswith("https://"):
        from app.ingestion.youtube import resolve_live
        source=resolve_live(source)
    cap=cv2.VideoCapture(source,cv2.CAP_FFMPEG,[cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,15000,cv2.CAP_PROP_READ_TIMEOUT_MSEC,15000])
    if not cap.isOpened():
        parser.error("Could not open the source")
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"images").mkdir(exist_ok=True)
    path=args.output/"dataset.json"
    dataset=json.loads(path.read_text()) if path.exists() else {"version":1,"classes":["person"],"frames":[]}
    sequence=hashlib.sha256(args.source.encode()).hexdigest()[:12]
    prefix=f"{args.scenario}-{time.time_ns()}"
    fps=cap.get(cv2.CAP_PROP_FPS) or 25
    try:
        captured=0
        for index in range(args.frames*args.stride):
            ok,image=cap.read()
            if not ok:
                break
            if index%args.stride:
                continue
            if args.blur:
                image=cv2.GaussianBlur(image,(15,15),4)
            name=f"{prefix}-{captured:03}.jpg"
            if not cv2.imwrite(str(args.output/"images"/name),image):
                raise RuntimeError("Could not write reference frame")
            dataset["frames"].append({"image":f"images/{name}","scenario":args.scenario,
                "source_id":sequence,"sequence":sequence+(':blurred' if args.blur else ''),"timestamp":round(1+index/fps,3),"split":"development",
                "reviewed":False,"synthetic":args.blur,"labels":[]})
            captured+=1
    finally:
        cap.release()
    path.write_text(json.dumps(dataset,indent=2),encoding="utf-8")
    print(f"Saved {captured} unreviewed frames to {path}. Label them before accuracy evaluation.")


if __name__=="__main__":
    main()
