"""One-to-one detection, tracking, counting, and event evaluation on reviewed labels."""
from collections import Counter
from statistics import mean

from app.inference.detection_geometry import iou


def match_boxes(predictions, labels, threshold=.5):
    used = set()
    matches = []
    false_positive = []
    for index in sorted(range(len(predictions)), key=lambda i: -predictions[i].get("confidence",1)):
        pred = predictions[index]
        candidates = [(iou(pred["bbox"], truth["bbox"]), j) for j,truth in enumerate(labels)
                      if j not in used and truth["object_type"] == pred["object_type"]]
        overlap, match = max(candidates, default=(0,-1))
        if overlap >= threshold:
            used.add(match)
            matches.append((index,match))
        else:
            false_positive.append(index)
    return matches, false_positive, [i for i in range(len(labels)) if i not in used]


def evaluate_frames(frames, predictions, classes):
    tp=fp=fn=0
    by_class = {c: {"tp":0,"fp":0,"fn":0} for c in classes}
    count_errors = []
    scored = {c: [] for c in classes}
    ground_truth_counts = Counter()
    for frame, raw in zip(frames,predictions):
        labels = [b for b in frame["labels"] if b["object_type"] in classes]
        preds = [b for b in raw if b["object_type"] in classes and b.get("confirmed",True)]
        region=frame.get("evaluation_region",[0,0,1,1])
        inside=lambda b: region[0] <= (b[0]+b[2])/2 <= region[2] and region[1] <= (b[1]+b[3])/2 <= region[3]
        labels=[b for b in labels if inside(b["bbox"])]
        preds=[b for b in preds if inside(b["bbox"])]
        # Ambiguous/unlabelable objects can be explicitly excluded, never inferred.
        ignored = frame.get("ignore_boxes", [])
        preds = [p for p in preds if not any(iou(p["bbox"], box) > .3 for box in ignored)]
        matches, false_pos, false_neg = match_boxes(preds, labels)
        matched = {a for a,b in matches}
        tp+=len(matches); fp+=len(false_pos); fn+=len(false_neg)
        for j,p in enumerate(preds):
            name = p["object_type"]
            by_class[name]["tp" if j in matched else "fp"] += 1
            scored[name].append((p.get("confidence",1), j in matched))
        for j in false_neg:
            by_class[labels[j]["object_type"]]["fn"] += 1
        ground_truth_counts.update(b["object_type"] for b in labels)
        gt = Counter(b["object_type"] for b in labels)
        pd = Counter(b["object_type"] for b in preds)
        count_errors.append(sum(abs(gt[c]-pd[c]) for c in classes))
    aps=[]
    for name, values in by_class.items():
        a,b,c=values["tp"],values["fp"],values["fn"]
        values["precision"]=a/(a+b) if a+b else None
        values["recall"]=a/(a+c) if a+c else None
        total=ground_truth_counts[name]
        if total:
            points=[]; correct=0
            for rank,(_,hit) in enumerate(sorted(scored[name],key=lambda x:-x[0]),1):
                correct+=int(hit)
                points.append((correct/total,correct/rank))
            ap=sum(max((p for r,p in points if r>=step/100),default=0) for step in range(101))/101
            values["ap50"]=ap
            aps.append(ap)
        else:
            values["ap50"]=None
    return {"tp":tp,"fp":fp,"fn":fn,"precision":tp/(tp+fp) if tp+fp else None,
            "recall":tp/(tp+fn) if tp+fn else None,"map50":mean(aps) if aps else None,
            "count_mean_absolute_error":mean(count_errors) if count_errors else None,"per_class":by_class}


def evaluate_tracking(frames, predictions, tracker_factory):
    previous={}; trackers={}; switches=matched=total=0
    for frame,preds in zip(frames,predictions):
        sequence=frame.get("sequence",frame["image"])
        tracker=trackers.setdefault(sequence, None)
        if tracker is None:
            tracker=trackers[sequence]=tracker_factory()
        tracks=tracker.update([dict(p) for p in preds], now=frame.get("timestamp",1.))
        labeled=[b for b in frame["labels"] if b.get("track_id") is not None]
        total+=len(labeled)
        visible=[(p,t) for p,t in zip(preds,tracks) if t is not None]
        pairs,_,_=match_boxes([p for p,t in visible],labeled)
        for p,g in pairs:
            tid=visible[p][1].track_id
            key=(sequence,labeled[g]["track_id"])
            if key in previous and previous[key]!=tid:
                switches+=1
            previous[key]=tid
            matched+=1
    return {"id_switches":switches,"matched_labeled_track_observations":matched,
            "labeled_track_observations":total,"coverage":matched/total if total else None}


def evaluate_events(expected, observed, tolerance=2.):
    used=set(); delays=[]
    for event in sorted(observed,key=lambda e:e["timestamp"]):
        candidates=[(abs(event["timestamp"]-truth["timestamp"]),j) for j,truth in enumerate(expected)
                    if j not in used and truth["type"]==event["type"] and truth.get("rule_id")==event.get("rule_id")
                    and (truth.get("sequence") is None or truth["sequence"]==event.get("sequence"))
                    and abs(event["timestamp"]-truth["timestamp"])<=tolerance]
        _,j=min(candidates,default=(None,None))
        if j is not None:
            used.add(j); delays.append(event["timestamp"]-expected[j]["timestamp"])
    return {"matched":len(used),"missed":len(expected)-len(used),"false_alerts":len(observed)-len(used),
            "mean_alert_delay_secs":mean(delays) if delays else None}
