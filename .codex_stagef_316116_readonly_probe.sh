#!/usr/bin/env bash
set -u
export TZ=Asia/Shanghai

echo SNAPSHOT_BEGIN
date -Ins
hostname

echo SQUEUE
squeue -j 316116,316117 -o '%.18i|%.12P|%.28j|%.10u|%.2t|%.16M|%.20S|%.30R|%.8C'

echo SACCT
sacct -j 316116,316117 --starttime 2026-07-11 -X -n -P \
  -o JobIDRaw,JobName,Partition,State,ExitCode,Elapsed,Start,End,NodeList,AllocCPUS

echo JOB_316116
scontrol show job -dd 316116 | tr ' ' '\n' | \
  grep -E '^(JobId|JobState|Reason|Dependency|RunTime|TimeLimit|StartTime|EndTime|NodeList|NumCPUs|StdOut|StdErr)='
echo JOB_316117
scontrol show job -dd 316117 | tr ' ' '\n' | \
  grep -E '^(JobId|JobState|Reason|Dependency|RunTime|TimeLimit|StartTime|EndTime|NodeList|NumCPUs|StdOut|StdErr)='

out=/storage/penghongen/AdaLigand/Ori_Data/logs/f/adaligand_f_316116.out
err=/storage/penghongen/AdaLigand/Ori_Data/logs/f/adaligand_f_316116.err
echo LOG_STATS
for p in "$out" "$err"; do
  if [[ -f "$p" ]]; then
    stat -Lc '%n|inode=%i|size=%s|mtime=%y|blocks=%b' "$p"
    wc -l "$p"
  else
    echo "$p|ABSENT"
  fi
done
echo OUT_TAIL
tail -n 40 "$out" 2>/dev/null || true
echo ERR_TAIL
tail -n 80 "$err" 2>/dev/null || true
echo PROGRESS_TAIL
grep -aE 'Done [0-9]+ tasks|Done [0-9]+ out of|Parallel\(n_jobs=12\)|F_N_JOBS|readiness|Heartbeat|heartbeat' \
  "$out" "$err" 2>/dev/null | tail -n 40 || true

echo LOCKS
for p in \
  /home/penghongen/after_lock_316116 \
  /home/penghongen/try_lock_316116 \
  /home/penghongen/kill_lock_316116 \
  /home/penghongen/pre_lock_316116 \
  /home/penghongen/child_pgid_316116; do
  if [[ -e "$p" || -L "$p" ]]; then
    stat -Lc '%n|type=%F|inode=%i|mode=%a|size=%s|mtime=%y' "$p"
  else
    echo "$p|ABSENT"
  fi
done

echo SSTAT
sstat -j 316116.batch -P -n -o JobID,AveCPU,MaxRSS,AveRSS,MaxDiskRead,MaxDiskWrite 2>&1 || true
echo NODE_PROCESS_PROBE
ssh -o BatchMode=yes -o ConnectTimeout=8 cnode04 \
  "ps -eo pid=,ppid=,pgid=,stat=,etime=,pcpu=,pmem=,args= --sort=pid | grep -E '(f_quality.py|joblib.externals.loky|popen_loky|Chimera|chimera|MapQ|mapq|resume_f_316116|run_cmd_316116)' | grep -v grep || true" 2>&1 || true

echo SNAPSHOT_END
date -Ins
