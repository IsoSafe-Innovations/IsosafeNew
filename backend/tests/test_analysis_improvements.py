import asyncio
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from app.inference.options import AnalysisOptions
from app.inference.detection_geometry import crop_windows, suppress
from app.inference.telemetry import AnalysisTelemetry, present_analysis
from app.inference.plates import PlateConsensus, locate_plate
from app.inference.benchmark import evaluate_frames, evaluate_events
from app.inference.tracker import CentroidTracker
from app.rules.engine import CameraRuleEngine
from app.rules.validation import validate_rules


def detection(x=.2, name="person", score=.9):
    return {"object_type":name,"bbox":[x,.2,x+.1,.5],"confidence":score,"confirmed":score>=.35}


def test_invalid_analysis_options_are_rejected():
    for value in [{"preset":"unknown"},{"input_size":999},{"confirmation_frames":0},
                  {"person_confidence":-1},{"regions":[{"x1":.8,"y1":0,"x2":.2,"y2":1}]}]:
        with pytest.raises(ValidationError):
            AnalysisOptions.model_validate(value)


def test_tiled_crops_are_bounded_and_duplicates_are_merged_by_class():
    windows=crop_windows(100,80,{"tiled":True,"regions":[{"x1":0,"y1":0,"x2":1,"y2":1}]})
    assert len(windows)==5
    assert all(0<=a<c<=100 and 0<=b<d<=80 for a,b,c,d in windows)
    duplicates=[detection(),detection(.201),detection(.2,"car")]
    assert len(suppress(duplicates))==2


@pytest.mark.parametrize("kind",["bytetrack","botsort"])
def test_motion_tracker_keeps_ids_when_detection_order_changes_and_after_occlusion(kind):
    from app.inference.advanced_tracker import MotionTracker
    tracker=MotionTracker(kind,2)
    first=tracker.update([detection(.2),detection(.6,"car")],now=1)
    second=tracker.update([detection(.6,"car"),detection(.2)],now=1.1)
    assert first[0].track_id==second[1].track_id
    assert first[1].track_id==second[0].track_id
    assert tracker.session_counts=={"person":1,"car":1}
    tracker.update([],now=1.2)
    recovered=tracker.update([detection(.2)],now=1.3)
    assert recovered[0].track_id==first[0].track_id
    assert tracker.session_counts["person"]==1


def test_low_confidence_object_cannot_create_confirmed_track():
    from app.inference.advanced_tracker import MotionTracker
    tracker=MotionTracker("bytetrack",2)
    for n in range(5):
        assert tracker.update([detection(score=.15)],now=n+1)==[None]
    assert not tracker.session_counts


def test_ingestion_without_results_is_not_ready_analysis():
    assert present_analysis(None)["ready"] is False
    assert present_analysis({"state":"warming_up","processed_fps":0})["ready"] is False
    old=present_analysis({"state":"running","last_result_ts":10,"frame_ts":9,"processed_fps":5},now=30)
    assert old["state"]=="stalled" and old["processed_fps"]==0 and old["frame_age_secs"]==21


async def test_telemetry_reports_actual_processed_progress(monkeypatch):
    async def save(*args,**kwargs):
        pass
    monkeypatch.setattr("app.inference.telemetry.get_redis",lambda:SimpleNamespace(set=save))
    telemetry=AnalysisTelemetry("test",{})
    await telemetry.record(time.time()-.2,50)
    snapshot=present_analysis(telemetry.snapshot())
    assert snapshot["ready"] and snapshot["processed_frames"]==1
    assert snapshot["inference_ms"]==50


def test_plate_reader_requires_consensus_and_rejects_branding():
    consensus=PlateConsensus(3)
    assert consensus.add("TOYOTA",.99,1) is None
    assert consensus.add("ABC123",.9,2) is None
    assert consensus.add("ABC123",.9,2) is None  # same frame is not extra evidence
    assert consensus.add("ABC123",.8,3) is None
    text,confidence=consensus.add("ABC123",.9,4)
    assert text=="ABC123" and confidence>.85
    assert PlateConsensus(3).add("ABC123",.2,1) is None


def test_plate_localization_abstains_on_distant_or_blurred_regions(monkeypatch):
    monkeypatch.delenv("PLATE_MODEL",raising=False)
    image=np.zeros((200,300,3),np.uint8)
    cv2.rectangle(image,(90,130),(210,165),(255,255,255),2)
    cv2.putText(image,"ABC123",(95,155),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
    crop,state=locate_plate(image,[0,0,1,1],64,20)
    assert crop is not None and state=="candidate"
    assert locate_plate(image,[0,0,.1,.1],64,20)[0] is None
    blurred=cv2.GaussianBlur(image,(41,41),10)
    assert locate_plate(blurred,[0,0,1,1],64,60)[0] is None


def test_intrusion_requires_sustained_zone_evidence():
    zone={"id":"z","polygon":[[0,0],[1,0],[1,1],[0,1]]}
    rule={"id":"intrusion","type":"zone_intrusion","zone_id":"z","min_frames":3}
    engine=CameraRuleEngine("test",[zone],[rule])
    tracker=CentroidTracker()
    events=[]
    for n in range(5):
        events+=engine.evaluate(tracker.update([detection()],now=100+n*.1),now=100+n*.1)
    assert len(events)==1
    flicker=CameraRuleEngine("test",[zone],[rule])
    tracker=CentroidTracker()
    track=tracker.update([detection()],now=100)[0]; track.hits=10
    assert flicker.evaluate([track],now=100)==[]
    track.confident=False
    assert flicker.evaluate([track],now=100.1)==[]
    track.confident=True
    assert flicker.evaluate([track],now=100.2)==[]


def test_crossing_counts_multiple_people_even_when_alert_is_on_cooldown():
    zone={"id":"line","line":[[0,.5],[1,.5]]}
    rule={"id":"entry","type":"line_crossing","zone_id":"line","direction":"positive","count_as":"entry","cooldown_seconds":100}
    engine=CameraRuleEngine("test",[zone],[rule])
    tracker=CentroidTracker()
    def person(x,y):
        return {"object_type":"person","bbox":[x,y-.04,x+.05,y+.04],"confidence":.9}
    events=[]
    for n,points in enumerate([[(.2,.45),(.6,.4)],[(.2,.55),(.6,.45)],[(.2,.56),(.6,.55)]]):
        tracks=tracker.update([person(*p) for p in points],now=100+n*.1)
        events+=engine.evaluate(tracks,now=100+n*.1)
    assert len(events)==1
    assert engine.crossing_counts["entry:positive:person"]==2
    assert len(engine.crossing_events)==2


def test_entry_counts_require_a_direction_and_valid_line():
    with pytest.raises(ValueError):
        validate_rules([{"type":"line_crossing","zone_id":"z","count_as":"entry","direction":"both"}],[{"id":"z","line":[[0,.5],[1,.5]]}])
    with pytest.raises(ValueError):
        validate_rules([{"type":"line_crossing","zone_id":"z"}],[])


def test_benchmark_penalizes_missed_objects_duplicate_predictions_and_false_alerts():
    label=detection()
    frames=[{"labels":[label]}]
    result=evaluate_frames(frames,[[detection(),detection(.201),detection(.7)]],["person"])
    assert (result["tp"],result["fp"],result["fn"])==(1,2,0)
    missed=evaluate_frames(frames,[[]],["person"])
    assert missed["recall"]==0 and missed["fn"]==1
    events=evaluate_events([{"type":"loitering","rule_id":"l","timestamp":10}],
        [{"type":"loitering","rule_id":"l","timestamp":11},{"type":"loitering","rule_id":"l","timestamp":12}])
    assert events=={"matched":1,"missed":0,"false_alerts":1,"mean_alert_delay_secs":1}


def test_scheduler_is_fair_and_uses_newest_frame():
    from app.pipeline.runner import Pipeline
    from app.ingestion.streams import Frame
    pipeline=Pipeline.__new__(Pipeline)
    pipeline.settings=SimpleNamespace(inference_batch_size=2,max_analysis_frame_age_secs=3)
    pipeline._batch_cursor=0
    pipeline.streams={}
    for cid in ["a","b","c","d"]:
        queue=asyncio.Queue()
        for seq in (0,1):
            queue.put_nowait(Frame(cid,None,time.time(),seq))
        pipeline.streams[cid]=SimpleNamespace(queue=queue,health=SimpleNamespace(frames_dropped=0))
    first=pipeline._collect_batch(); second=pipeline._collect_batch()
    assert {f.camera_id for f in first+second}=={"a","b","c","d"}
    assert all(f.seq==1 for f in first+second)


async def test_youtube_segment_decoding_is_paced(monkeypatch):
    from app.ingestion import streams
    waits=[]
    class Capture:
        frames=0
        def isOpened(self): return True
        def get(self,key): return 30
        def read(self):
            self.frames+=1
            return (True,np.zeros((8,8,3),np.uint8)) if self.frames<=3 else (False,None)
        def release(self): pass
    async def pause(seconds): waits.append(seconds)
    stream=streams.CameraStream("test","unused","youtube")
    monkeypatch.setattr(stream,"_open_capture",lambda _:Capture())
    monkeypatch.setattr(streams.asyncio,"sleep",pause)
    assert await stream._run_capture("unused",realtime=True)
    assert len(waits)==3 and all(seconds>0 for seconds in waits)


async def test_inference_timeout_recycles_only_owned_pool(monkeypatch):
    from concurrent.futures import Future
    from app.pipeline.runner import Pipeline
    recycled=[]
    class Pool:
        _processes={}
        def submit(self,*args): return Future()
        def shutdown(self,**kwargs): recycled.append(True)
    pipeline=Pipeline.__new__(Pipeline)
    pipeline.settings=SimpleNamespace(inference_timeout_secs=.01)
    pipeline.pool=Pool()
    monkeypatch.setattr(pipeline,"_make_pool",Pool)
    with pytest.raises(RuntimeError,match="failed to initialize"):
        await pipeline._infer([b"frame"])
    assert len(recycled)==2 and pipeline.pool is None


async def test_crossing_sessions_do_not_collide_when_camera_tracker_restarts():
    import uuid
    from app.inference.writer import DetectionWriter
    writer=DetectionWriter()
    event={"rule_id":"entry","track_id":1,"direction":"positive","count_as":"entry","object_type":"person","ts":100}
    a,b=uuid.uuid4(),uuid.uuid4()
    await writer.add_crossing("same-camera",{**event,"session_id":a})
    await writer.add_crossing("same-camera",{**event,"session_id":b})
    assert writer._crossings[0][1]==a and writer._crossings[1][1]==b
