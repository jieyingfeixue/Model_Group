#!/usr/bin/env python3
"""
SAM3 建筑物检测脚本
检测 037/038 可见光图片中的建筑物，输出 2D 标注框 JSON。

使用前需下载 SAM3 权重（在能上网的机器上）:
  pip install huggingface_hub
  python3 -c "
  from huggingface_hub import snapshot_download
  snapshot_download('facebook/sam3', local_dir='./sam3_weights')
  "
  tar czf sam3_weights.tar.gz sam3_weights/
  scp sam3_weights.tar.gz user@10.4.10.16:~/nas_write/

使用:
  python tools/sam3_detect_buildings.py \
    --seg_path "4_29/.../segment_000_..." \
    --ir_file "usb_ir__image_raw_000001_t000000.046.jpg"
"""
import sys, os, cv2, time, json, argparse, re
from pathlib import Path
import numpy as np

ROOT = '/data1/LHO/nas/LH_Dataset/LH_data_all_sensor'
CAMERAS = {
    '037': 'hikrobot_camera__DA8679037__image_raw',
    '038': 'hikrobot_camera__DA8679038__image_raw',
}
TS_RE = re.compile(r'_t(\d+\.\d+)')

def parse_ts(fname):
    m = TS_RE.search(fname)
    return float(m.group(1)) if m else None

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--seg_path', required=True)
    p.add_argument('--ir_file', help='IR filename for timestamp matching')
    p.add_argument('--checkpoint', default='./sam3_weights/sam3.pt')
    p.add_argument('--device', default='cuda:0')
    p.add_argument('--prompt', default='building. house. structure.')
    p.add_argument('--min_score', type=float, default=0.3)
    p.add_argument('--output_dir', help='output JSON dir')
    args = p.parse_args()

    # Load SAM3
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'sam3-main'))
    from sam3 import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor

    print(f'Loading SAM3 from {args.checkpoint}...')
    model = build_sam3_image_model(
        checkpoint_path=args.checkpoint, load_from_HF=False,
        device=args.device, eval_mode=True)
    processor = Sam3Processor(model)

    # Find images
    seg_dir = Path(ROOT) / args.seg_path
    targets = {}
    ir_ts = parse_ts(args.ir_file) if args.ir_file else 0

    for ck, cd in CAMERAS.items():
        cp = seg_dir / 'images' / cd
        if not cp.exists(): continue
        best, best_d = None, float('inf')
        for f in os.scandir(cp):
            if not f.is_file(): continue
            ts = parse_ts(f.name)
            if ts is None: continue
            d = abs(ts - ir_ts)
            if d < best_d: best_d, best = d, f.name
        if best:
            targets[ck] = (best, str(cp / best))
            print(f'{ck}: {best} (dt={best_d*1000:.1f}ms)')

    # Detect
    all_dets = {}
    for ck, (fname, fpath) in targets.items():
        print(f'\nDetecting {ck}: {fname}')
        img = cv2.cvtColor(cv2.imread(fpath), cv2.COLOR_BGR2RGB)
        t0 = time.time()
        processor.set_image(img)
        state = processor.set_text_prompt(args.prompt, {})
        dt = time.time() - t0

        dets = []
        for box, score in zip(state.get('pred_boxes', []), state.get('pred_scores', [])):
            s = float(score)
            if s < args.min_score: continue
            cx, cy, w, h = [float(x) for x in box]
            dets.append({'x1': cx-w/2, 'y1': cy-h/2, 'x2': cx+w/2, 'y2': cy+h/2,
                         'class': 'building', 'score': s})
        all_dets[ck] = dets
        print(f'  {len(dets)} buildings in {dt:.1f}s')
        for d in dets[:5]:
            print(f'  [{d["x1"]:.0f} {d["y1"]:.0f} {d["x2"]:.0f} {d["y2"]:.0f}] s={d["score"]:.3f}')

    # Save
    if args.output_dir:
        od = Path(args.output_dir) / args.seg_path / f'ir_ts_{ir_ts:.3f}'.replace('.','_')
        od.mkdir(parents=True, exist_ok=True)
        for ck, dets in all_dets.items():
            fp = od / f'{ck}_ts_{ir_ts:.3f}'.replace('.','_') + '.json'
            fp.write_text(json.dumps(dets, indent=2))
            print(f'Saved {len(dets)} → {fp}')

if __name__ == '__main__':
    main()
