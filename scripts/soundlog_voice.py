#!/usr/bin/env python3
import argparse,json
from pathlib import Path
from soundlog_memory.voice_calibration import prepare,state
from soundlog_memory.pipeline import Pipeline

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
 p.add_argument('command',choices=['prepare','status','extract','scores','calibrate','probe']);a=p.parse_args()
 with Pipeline(a.root).lock():
  if a.command in {'extract','scores','calibrate','probe'}:
   from soundlog_memory.voice_features import extract,similarities,calibrate,probe
   result=extract(a.root) if a.command=='extract' else calibrate(a.root) if a.command=='calibrate' else probe(a.root) if a.command=='probe' else similarities(a.root)
  else:result=prepare(a.root) if a.command=='prepare' else state(a.root)
 if a.command in {'extract','scores','calibrate','probe'}:
  print(json.dumps(result,ensure_ascii=False));return
 print(json.dumps({'samples':len(result['samples']),'sha256':result.get('sha256'),'counts':result.get('counts'),'matching':result.get('matching','not_started')},ensure_ascii=False))
if __name__=='__main__':main()
