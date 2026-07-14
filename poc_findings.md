# OMNIX Model Accuracy Findings

**Sampling method:** Every ~30th frame sampled from each predicted output video, reviewed manually.  Consistency prioritized over exhaustive frame-by-frame review.

**Confidence threshold used for all runs:** 0.5

---

## Helmet Model

| Clip | TP | FP | FN | Precision (TP/(TP+FP)) | Recall (TP/(TP+FN)) |
|---|---|---|---|---|---|
| test_video.mp4 | 22 | 1 | 1 | 95.7% | 95.7% |
| construction.mp4 | — | — | — | Excluded — see note below |

**Note on construction.mp4:** This clip was excluded from testing. Manual review of sampled frames showed it is indoor office/hallway surveillance footage of people in regular clothing — no construction site, scaffolding, or PPE of any kind is present. The model still produced "head"/"helmet" detections on this footage during the original prediction run, meaning those detections were false positives on out-of-domain content, not a fair test of the model's real-world accuracy. `test_video.mp4` is used as the sole clip for this report; a genuine second construction-site clip should be sourced before the next accuracy pass.

**Where the helmet model struggles:**
On `test_video.mp4` (a stylized 3D-animated safety training video, not real camera footage), the model performed strongly overall — 95.7% precision and recall. The one false positive (frame_0660) was a spurious "helmet" box drawn on a bare striped scaffolding pole with no person present, suggesting the model can occasionally key on high-contrast striped/cylindrical shapes similar to a helmet's curvature or color pattern. The one false negative (frame_0300) was a worn orange hard hat viewed from behind/above at an unusual angle, suggesting some sensitivity to viewing angle. One frame (frame_0120) showed an ambiguous white visor/welding-mask style headgear that the model did not flag either way — likely outside the model's trained definition of "helmet" rather than a true failure.

**Worst failure screenshots (3–4):**
1. frame_0660 (frames_helmet_testvideo) — FP: "helmet 0.55" box on bare scaffolding pole, no person present
2. frame_0300 (frames_helmet_testvideo) — FN: worn orange hard hat, no box drawn, unusual rear/top-down angle
3. frame_0120 (frames_helmet_testvideo) — ambiguous: white visor-style headgear, no detection either way
4. (construction.mp4, frame ~350-556 range) — illustrative of domain-mismatch false positives on non-construction footage; excluded from formal tally but worth keeping as a reference example

---

## Vest Model

| Clip | TP | FP | FN | Precision (TP/(TP+FP)) | Recall (TP/(TP+FN)) |
|---|---|---|---|---|---|
| test_video.mp4 | 0 | 1 | 0 | 0% | N/A — no true vests present in clip |
| construction.mp4 | — | — | — | Excluded — see note above |

**Where the vest model struggles:**
`test_video.mp4` turned out not to be a fair test of vest recall — every character in the clip wears the same navy jumpsuit with an orange safety harness, and none wear an actual high-visibility vest at any sampled frame. This means recall is untestable on this footage (no ground-truth positives exist to miss). The one detection that did fire (frame_0540, "safety-vest 0.58") was a false positive: the model appears to have mistaken the orange harness webbing across the torso for vest fabric, likely due to similar color and general torso-crossing strap pattern. This is a meaningful and specific failure mode — the vest model may be sensitive to orange straps/webbing in general, not just genuine hi-vis vests — but a proper accuracy read requires footage with workers actually wearing vests.

**Worst failure screenshots (3–4):**
1. frame_0540 (frames_vest_testvideo) — FP: "safety-vest 0.58" on harness webbing, no actual vest present

---

## Weak Model — Gloves

| Clip | TP | FP | FN | Precision (TP/(TP+FP)) | Recall (TP/(TP+FN)) |
|---|---|---|---|---|---|
| test_video.mp4 | 7 | 0 | Unknown | 100% | Not reliably computable — see note |

**Note on recall:** Gloves occupy a much smaller pixel area than helmets or vests, and at the resolution of standard sampled screenshots it was not possible to reliably distinguish "bare hand, correctly not boxed" from "gloved hand, model missed it" for roughly 13 of the 28 sampled frames. Unlike the helmet/vest review, this is a genuine measurement limitation rather than a scoring judgment call — a trustworthy recall number would require either full-resolution hand crops or reviewing the source video directly to confirm which frames show gloves. The 7 confirmed true positives (all showing a gloved hand actively gripping equipment — a drill, harness clip, or ladder rung) had zero false positives, which is a good precision signal as far as it goes.

Also worth noting: this model, loaded from `gloves_model/weights/best.pt`, also produces `helmet` and `head` class detections — it appears to be a multi-class model covering more than gloves alone, not a dedicated single-purpose gloves detector. This should be accounted for when interpreting "gloves model accuracy" going forward.

**Where this model struggles:**
Based on available evidence, the model correctly identifies gloves when hands are gripping tools or equipment in a clear, unobstructed pose. It's unclear from this test whether it misses gloves in more passive poses (hands at sides, hands near face) since ground truth couldn't be confirmed for those frames. Given gloves' known 78.9% mAP from training, some recall gap is expected, but this clip did not provide enough resolution to quantify where it occurs.

**Worst failure screenshots (3–4):**
_(None confidently identified as failures in this pass — see recall note above. Revisit with full-resolution crops if a rigorous gloves accuracy number is needed.)_

---

## Summary — which model needs retraining next

Ranked by verified precision/recall from this test round: **helmet (95.7%/95.7%)** performed strongest, **vest (0%/untestable)** was inconclusive only because `test_video.mp4` contained no actual vests to detect — not a confirmed model failure, but its one false positive (mistaking harness webbing for vest fabric) is a real, specific weakness worth investigating with proper vest footage. **Gloves (100% precision on confirmed detections, recall unmeasurable)** is the least conclusively tested — combined with its already-known 78.9% training mAP (the lowest of the three) and its unexpected multi-class behavior, **gloves is the clearest candidate for a dedicated retraining and proper re-test with vest-and-glove-specific footage**, ideally using full-resolution frame review rather than thumbnail sampling.